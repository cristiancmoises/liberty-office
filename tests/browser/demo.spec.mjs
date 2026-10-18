import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';

const origin=process.env.LIBERTY_DEMO_ORIGIN||'http://localhost:8097';
function zipMember(path,member){
 return execFileSync('python3',['-c','import sys,zipfile; sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read(sys.argv[2]))',path,member],{encoding:'utf8'});
}
async function open(page,name){
 await page.goto(origin+'/demo?lang=pt-BR');await page.locator('.app-card').filter({hasText:name}).click();
 const editor=page.frameLocator('#demo-frame iframe');await expect(editor.locator('html')).toHaveAttribute('data-liberty-state','ready',{timeout:120000});return editor;
}

test('anonymous WordCraft edits and exports a real DOCX with native keyboard input',async({page},info)=>{
 await page.setViewportSize({width:1440,height:1000});const editor=await open(page,'WordCraft');
 await expect(editor.locator('canvas')).toBeVisible();
 await editor.locator('canvas').click({position:{x:310,y:200}});
 await page.waitForTimeout(500); // eframe installs its text input after the New-document click.
 await page.keyboard.type('Liberty native document regression.',{delay:100});
 const pending=page.waitForEvent('download');await page.keyboard.press('Control+s');
 const download=await pending,path=info.outputPath('native.docx');await download.saveAs(path);
 expect(zipMember(path,'word/document.xml')).toContain('Liberty native document regression.');
 await expect(page.locator('.demo-banner')).toContainText('Sem conta, sem uploads');
});

test('anonymous GridCraft edits cells and exports the entered formula and calculated value',async({page},info)=>{
 await page.setViewportSize({width:1440,height:1000});const editor=await open(page,'GridCraft');
 await editor.locator('canvas').click({position:{x:52,y:223}});await page.keyboard.type('42',{delay:200});await page.waitForTimeout(300);await page.keyboard.press('Enter');await page.waitForTimeout(300);
 await editor.locator('canvas').click({position:{x:104,y:223}});await page.keyboard.type('=6*7',{delay:200});await page.waitForTimeout(300);await page.keyboard.press('Enter');await page.waitForTimeout(300);
 const pending=page.waitForEvent('download');await page.keyboard.press('Control+s');
 const download=await pending,path=info.outputPath('native.xlsx');await download.saveAs(path);
 const sheet=zipMember(path,'xl/worksheets/sheet1.xml');expect(sheet).toContain('<f>6*7</f>');expect(sheet).toContain('<v>42</v>');
});

test('demo remains isolated and usable at mobile widths without upload APIs',async({page})=>{
 await page.route('**/demo/apps',async route=>{
  const response=await route.fetch(),catalog=await response.json();
  for(const app of catalog.apps)if(app.id==='wordcraft')app.url+='?light';
  await route.fulfill({response,json:catalog});
 });
 await page.setViewportSize({width:390,height:844});await page.goto(origin+'/demo');
 await expect(page.locator('.app-card')).toHaveCount(13);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 const apps=await (await page.request.get(origin+'/demo/apps')).json(),word=apps.apps.find(app=>app.id==='wordcraft');
 await page.locator('.app-card[title="WordCraft"]').click();
 await expect(page.frameLocator('#demo-frame iframe').locator('#__liberty-config')).toHaveCount(1);
 const frame=page.frames().find(frame=>frame.url().includes('/demo/runtime/wordcraft/'));
 await expect(frame.locator('.light-document')).toBeVisible();
 await frame.locator('.light-document').press('End');await frame.locator('.light-document').pressSequentially(' Native mobile typing.');
 await expect(frame.locator('.light-document')).toContainText('Native mobile typing.');
 const pending=page.waitForEvent('download');await frame.getByRole('button',{name:'Download copy',exact:true}).click();
 const download=await pending,stream=await download.createReadStream(),chunks=[];
 for await(const chunk of stream)chunks.push(chunk);
 expect(download.suggestedFilename()).toBe('document.html');expect(Buffer.concat(chunks).toString()).toContain('Native mobile typing.');
 await expect(frame.locator('.light-status')).toContainText('Download started.');
 await expect(frame.getByRole('button',{name:'Open TXT/HTML',exact:true})).toBeVisible();
 expect(await frame.evaluate(()=>{try{parent.document.body;return false}catch(error){return error.name==='SecurityError'}})).toBe(true);
 const denied=await frame.evaluate(async()=>{try{await showDirectoryPicker();return false}catch(error){return error.name==='NotAllowedError'}});expect(denied).toBe(true);
 const demoOrigin=new URL(word.url).origin;
 expect((await page.request.get(demoOrigin+'/api/auth/status')).status()).toBe(404);
 const blockedUpload=await page.request.post(demoOrigin+'/api/files',{data:'no upload'});
 // The public proxy rejects POST before routing; direct backend tests return 404.
 expect([403,404]).toContain(blockedUpload.status());
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('light HTML import remains inert and exports only text plus editor formatting',async({page})=>{
 await open(page,'WordCraft');const frame=page.frames().find(frame=>frame.url().includes('/demo/runtime/wordcraft/'));
 const result=await frame.evaluate(async()=>{
  const {mountLightEditor}=await import('./__liberty/light-editor.mjs');let saved='';
  const hostile='<h1>Safe title</h1><img src="/missing-image" onerror="window.htmlExecuted=true"><script>window.htmlExecuted=true</script><a href="javascript:window.htmlExecuted=true">A link</a>';
  window.showOpenFilePicker=async()=>[{getFile:async()=>new File([hostile],'fixture.html',{type:'text/html'})}];
  mountLightEditor(window,{onState(){},onSave:async blob=>{saved=await blob.text()}});
  document.querySelectorAll('.light-toolbar button')[4].click();
  await new Promise(resolve=>setTimeout(resolve,50));
  const area=document.querySelector('.light-document');area.focus();
  const clipboard=new DataTransfer();clipboard.setData('text/html','<img src=x onerror="window.htmlExecuted=true">');clipboard.setData('text/plain','Plain pasted text');
  area.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:clipboard}));
  document.querySelector('.light-toolbar button:last-child').click();await new Promise(resolve=>setTimeout(resolve,50));
  return {saved,executed:!!window.htmlExecuted,active:document.querySelector('.light-document').querySelector('script,img,a')!==null};
 });
 expect(result.executed).toBe(false);expect(result.active).toBe(false);expect(result.saved).toContain('Safe title');
 expect(result.saved).toContain('Plain pasted text');
 expect(result.saved).not.toMatch(/<script|<img|<a\s|\sonerror=/i);
});
