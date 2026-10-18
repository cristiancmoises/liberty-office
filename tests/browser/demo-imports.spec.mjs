import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
const origin=process.env.LIBERTY_DEMO_ORIGIN;
if(!origin)throw Error('Set an explicit isolated demo portal.');
async function open(page,name,{light=false}={}){
 if(light)await page.route('**/demo/apps',async route=>{
  const response=await route.fetch(),catalog=await response.json();
  for(const app of catalog.apps)if(app.id==='wordcraft')app.url+='?light';
  await route.fulfill({response,json:catalog});
 });
 await page.goto(origin+'/demo');await page.locator('.app-card[title="'+name+'"]').click();
 await expect(page.frameLocator('#demo-frame iframe').locator('html')).toHaveAttribute('data-liberty-state','ready',{timeout:120000});
 return page.frames().find(frame=>frame.url().includes('/demo/runtime/'));
}
async function choose(page,frame,file,{native=false,backstage=false}={}){
 if(!native)await expect(frame.getByRole('button',{name:'Open TXT/HTML',exact:true})).toBeVisible();
 if(backstage){
  // Word's text field consumes global shortcuts. These are the verified
  // File -> Open -> Browse controls at the fixed native qualification viewport.
  await frame.locator('canvas').click({position:{x:27,y:53}});await page.waitForTimeout(150);
  await frame.locator('canvas').click({position:{x:40,y:165}});await page.waitForTimeout(150);
 }
 const pending=page.waitForEvent('filechooser',{timeout:10000});
 if(backstage)await frame.locator('canvas').click({position:{x:280,y:92}});
 else if(native)await page.keyboard.press('Control+o');else await frame.getByRole('button',{name:'Open TXT/HTML',exact:true}).click();
 const picker=await pending;await picker.setFiles(file);
}
function zipText(path){return execFileSync('python3',['-c','import sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); print("\\n".join(z.read(n).decode("utf8",errors="ignore") for n in z.namelist() if n.endswith((".xml",".json",".txt"))))',path],{encoding:'utf8'})}
async function finish(page){
 page.once('dialog',dialog=>dialog.accept());await page.locator('#demo-close').click();await expect(page.locator('#demo-launcher')).toBeVisible();
 expect(page.frames().some(frame=>frame.url().includes('/demo/controller#'))).toBe(false);
}

test('light demo admits trusted local HTML without active markup, downloads a copy and clears',async({page})=>{
 const requests=[];page.on('request',request=>{if(request.url().startsWith('http'))requests.push({url:request.url(),method:request.method(),body:request.postData()})});
 const frame=await open(page,'WordCraft',{light:true}),name='local-private-synthetic-fixture.html';
 await choose(page,frame,{name,mimeType:'text/html',buffer:Buffer.from('<p>Browser-only import fixture</p><img src="/must-not-load" onerror="window.executed=true"><script>window.executed=true</script>')});
 await expect(frame.locator('.light-document')).toHaveText('Browser-only import fixture');
 expect(await frame.evaluate(()=>!!window.executed)).toBe(false);expect(await frame.locator('.light-document img, .light-document script').count()).toBe(0);
 await frame.locator('.light-document').press('End');await frame.locator('.light-document').pressSequentially(' edited locally');
 const pending=page.waitForEvent('download');await frame.getByRole('button',{name:'Download copy',exact:true}).click();
 const download=await pending,stream=await download.createReadStream(),chunks=[];for await(const chunk of stream)chunks.push(chunk);
 const output=Buffer.concat(chunks).toString();expect(output).toContain('Browser-only import fixture edited locally');expect(output).not.toMatch(/<script|<img/i);
 await finish(page);
 expect(requests.every(request=>['GET','HEAD'].includes(request.method))).toBe(true);
 expect(JSON.stringify(requests)).not.toContain(name);expect(JSON.stringify(requests)).not.toContain('Browser-only import fixture');expect(JSON.stringify(requests)).not.toContain('/must-not-load');
});

test('light picker, drop and file-paste share ten-file admission without reading the eleventh',async({page})=>{
 const frame=await open(page,'WordCraft',{light:true});
 await frame.evaluate(()=>{window.__fileReads=0;const read=Blob.prototype.arrayBuffer;Blob.prototype.arrayBuffer=function(){window.__fileReads++;return read.call(this)}});
 await choose(page,frame,{name:'first.txt',mimeType:'text/plain',buffer:Buffer.from('First local file')});
 await expect(frame.locator('.light-document')).toHaveText('First local file');
 for(const type of ['drop','paste']){
  await frame.evaluate(type=>{
   const data=new DataTransfer();data.items.add(new File(['Local '+type],type+'.txt',{type:'text/plain'}));
   const event=type==='drop'?new DragEvent(type,{bubbles:true,cancelable:true,dataTransfer:data}):new ClipboardEvent(type,{bubbles:true,cancelable:true,clipboardData:data});
   document.querySelector('.light-document').dispatchEvent(event);
  },type);
  await expect(frame.locator('.light-document')).toHaveText('Local '+type);
 }
 for(let n=3;n<10;n++){
  await choose(page,frame,{name:'replacement-'+n+'.txt',mimeType:'text/plain',buffer:Buffer.from('Replacement '+n)});
  await expect(frame.locator('.light-document')).toHaveText('Replacement '+n);
 }
 const reads=await frame.evaluate(()=>window.__fileReads);
 await choose(page,frame,{name:'eleventh.txt',mimeType:'text/plain',buffer:Buffer.from('Must not be read')});
 await expect(frame.locator('.light-status')).toContainText('10 files');
 expect(await frame.evaluate(()=>window.__fileReads)).toBe(reads);await expect(frame.locator('.light-document')).toHaveText('Replacement 9');
 await finish(page);
});

test('native clipboard capture rejects rich text imports and removes HTML flavors',async({page})=>{
 const frame=await open(page,'FigCraft');
 await frame.evaluate(()=>{
  window.__nativePastes=[];
  addEventListener('paste',event=>window.__nativePastes.push({text:event.clipboardData.getData('text'),html:event.clipboardData.getData('text/html')}),true);
  const data=new DataTransfer();data.setData('text/plain','<svg xmlns="http://www.w3.org/2000/svg"><rect width="100" height="100"/></svg>');
  document.querySelector('canvas').dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data}));
 });
 await expect(page.locator('#demo-status')).toContainText('Rich clipboard');
 expect(await frame.evaluate(()=>window.__nativePastes)).toEqual([]);
 await frame.evaluate(()=>{
  const data=new DataTransfer();data.setData('text/plain','Plain native clipboard fixture');data.setData('text/html','<svg><rect/></svg>');
  document.querySelector('canvas').dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data}));
 });
 expect(await frame.evaluate(()=>window.__nativePastes)).toEqual([{text:'Plain native clipboard fixture',html:''}]);await finish(page);
});

test('light filename controls keep native plain-paste behavior after bounded validation',async({page})=>{
 const frame=await open(page,'WordCraft',{light:true});
 const prevented=await frame.evaluate(()=>{
  const data=new DataTransfer();data.setData('text/plain','document-copy.html');
  const event=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data});
  document.querySelector('.light-heading input').dispatchEvent(event);return event.defaultPrevented;
 });
 expect(prevented).toBe(false);await finish(page);
});

for(const app of [{name:'WordCraft',file:'native-demo.txt',content:'Native local text import fixture.',expected:'Native local text import fixture.'},
 {name:'GridCraft',file:'native-demo.csv',content:'Name,Value\nLocal spreadsheet fixture,42',expected:'Local spreadsheet fixture'},
 {name:'DeckCraft',file:'native-demo.md',content:'Local presentation fixture\n  - Browser-only outline',expected:'Local presentation fixture'}]){
 test(app.name+' imports bounded native text, exports actual content and clears',async({page},info)=>{
  const requests=[];page.on('request',request=>{if(request.url().startsWith('http'))requests.push({url:request.url(),method:request.method(),body:request.postData()})});
  await page.setViewportSize({width:1440,height:1000});const frame=await open(page,app.name);
  await frame.locator('canvas').first().click({position:{x:310,y:200}});
  await choose(page,frame,{name:app.file,mimeType:'text/plain',buffer:Buffer.from(app.content)},{native:true,backstage:app.name==='WordCraft'});
  await page.waitForTimeout(750); // The native runner processes the delivered File asynchronously.
  let edit=null;
  if(app.name==='WordCraft'){
   edit=' Edited locally.';await frame.locator('canvas').click({position:{x:450,y:310}});
   await page.keyboard.press('End');await page.keyboard.type(edit,{delay:60});
  }else if(app.name==='GridCraft'){
   edit='Edited header';await frame.locator('canvas').click({position:{x:52,y:223}});
   await page.keyboard.type(edit,{delay:80});await page.keyboard.press('Enter');
  }
  const pending=page.waitForEvent('download',{timeout:15000});await page.keyboard.press('Control+s');
  const download=await pending,path=info.outputPath(download.suggestedFilename());await download.saveAs(path);
  const stream=await download.createReadStream(),chunks=[];for await(const chunk of stream)chunks.push(chunk);
  const bytes=Buffer.concat(chunks),content=bytes.subarray(0,2).toString()==='PK'?zipText(path):bytes.toString();
  expect(content).toContain(app.expected);if(edit)expect(content).toContain(edit.trim());await finish(page);
  expect(requests.every(request=>['GET','HEAD'].includes(request.method))).toBe(true);
  expect(JSON.stringify(requests)).not.toContain(app.file);expect(JSON.stringify(requests)).not.toContain(app.content);
 });
}
