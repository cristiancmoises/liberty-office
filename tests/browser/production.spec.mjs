import {test,expect} from '@playwright/test';
import {readFileSync,writeFileSync} from 'node:fs';import {createHmac} from 'node:crypto';
import {execFileSync} from 'node:child_process';
const seedPath=process.env.LIBERTY_ACCEPTANCE_SEED;
if(!seedPath)throw Error('Use scripts/docker_acceptance.sh with an empty isolated volume.');
const seed=JSON.parse(readFileSync(seedPath,'utf8'));
function totp(secret){let bits='';for(const c of secret.toUpperCase())bits+='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'.indexOf(c).toString(2).padStart(5,'0');const key=Buffer.from(bits.match(/.{8}/g).map(b=>parseInt(b,2)));const counter=Buffer.alloc(8);counter.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));const hash=createHmac('sha1',key).update(counter).digest(),offset=hash[19]&15;return String((hash.readUInt32BE(offset)&0x7fffffff)%1e6).padStart(6,'0')}

test('MFA recovery, 13 graphical editors and isolated file bridge',async({page})=>{
 await page.setViewportSize({width:1440,height:1000});
 await page.goto(seed.origin+'/?lang=pt-BR');await page.getByLabel('Usuário',{exact:true}).fill(seed.username);await page.getByLabel('Senha',{exact:true}).fill(seed.password);await page.getByRole('button',{name:'Continuar',exact:true}).click();
 await page.getByLabel('Código MFA ou recuperação').fill(seed.recovery);await page.getByRole('button',{name:'Entrar com segurança'}).click();
 await expect(page.locator('.secret')).toBeVisible();const secret=await page.locator('.secret').textContent();
 await page.getByLabel('Código de 6 dígitos').fill(totp(secret));await page.getByRole('button',{name:'Ativar e entrar'}).click();
 seed.recovery=await page.locator('.recovery-codes code').first().textContent();writeFileSync(seedPath,JSON.stringify(seed),{mode:0o600});
 await page.getByRole('button',{name:'Guardei os códigos. Abrir meu espaço'}).click();await expect(page.locator('#workspace')).toBeVisible();
 const apps=(await (await page.request.get(seed.origin+'/api/apps')).json()).apps;expect(apps).toHaveLength(13);
 for(const app of apps){
  await test.step(app.name,async()=>{
   await page.getByRole('button',{name:'Aplicativos',exact:true}).click();
   await page.locator('.app-card').filter({hasText:app.name}).first().click();
   const editor=page.frameLocator('.editor iframe');await expect(editor.locator('html[data-liberty-state="ready"]')).toHaveCount(1,{timeout:60000});await expect(editor.locator('canvas').first()).toBeVisible({timeout:120000});
   await expect.poll(async()=>{const frame=page.frames().find(f=>f.url().startsWith(seed.editorOrigin+'/runtime/'));if(!frame)return false;return frame.evaluate(()=>[...document.querySelectorAll('canvas')].some(c=>c.width>300&&c.height>200))},{timeout:120000}).toBe(true);
   const frame=page.frames().find(f=>f.url().startsWith(seed.editorOrigin+'/runtime/'));
   expect(await frame.evaluate(()=>{try{return parent.document.body?'unsafe':'unknown'}catch(e){return e.name}})).toBe('SecurityError');
   expect(await frame.evaluate(async()=> (await fetch('/api/auth/status')).status)).toBe(404);
   if(app.id==='wordcraft'){
    // The HTML already contains a canvas before WASM starts. Prove that the
    // original engine accepts native input and that Drive gets its real DOCX.
    await editor.locator('canvas').click({position:{x:310,y:200}});await page.waitForTimeout(500);
    await page.keyboard.type('Liberty authenticated native editing.',{delay:100});await page.keyboard.press('Control+s');
    await expect(page.locator('.editor-status')).toContainText('Salvo no Drive',{timeout:60000});
    const nativeFiles=(await (await page.request.get(seed.origin+'/api/files')).json()).files;
    const document=nativeFiles.find(file=>/\.docx$/i.test(file.name));expect(document).toBeTruthy();
    const bytes=await (await page.request.get(seed.origin+'/api/files/'+document.id+'/content')).body();
    const xml=execFileSync('python3',['-c','import sys,io,zipfile; sys.stdout.buffer.write(zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).read("word/document.xml"))'],{input:bytes,encoding:'utf8'});
    expect(xml).toContain('Liberty authenticated native editing.');
    const chooserPromise=page.waitForEvent('filechooser');
    const selected=frame.evaluate(async()=>{const handles=await window.showOpenFilePicker({multiple:true,types:[{accept:{'text/plain':['.txt']}}]});return Promise.all(handles.map(async h=>({name:h.name,text:await (await h.getFile()).text()})))});
    const chooser=await chooserPromise;await chooser.setFiles([{name:'local-one.txt',mimeType:'text/plain',buffer:Buffer.from('one')},{name:'local-two.txt',mimeType:'text/plain',buffer:Buffer.from('two')}]);
    expect(await selected).toEqual([{name:'local-one.txt',text:'one'},{name:'local-two.txt',text:'two'}]);
    // A fresh document must establish a fresh channel before exporting below.
    await frame.goto(frame.url());await expect(editor.locator('html[data-liberty-state="ready"]')).toHaveCount(1,{timeout:60000});await expect(editor.locator('canvas').first()).toBeVisible({timeout:120000});
   }
   const name='bridge-'+app.id+'.txt';await frame.evaluate(name=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['Liberty bridge smoke'],{type:'text/plain'}));a.download=name;a.click()},name);
   await expect(page.locator('.editor-status')).toContainText('Salvo no Drive',{timeout:60000});
   const files=(await (await page.request.get(seed.origin+'/api/files')).json()).files;expect(files.some(f=>f.name===name)).toBe(true);
   await page.locator('.editor-top').getByRole('button',{name:'Fechar',exact:true}).click();
   await page.getByRole('dialog').getByRole('button',{name:'Confirmar',exact:true}).click();await expect(page.locator('.editor')).toHaveCount(0);
  });
 }
 await test.step('browser storage identity change removes OPFS from the previous account',async()=>{
  const auth=await (await page.request.get(seed.origin+'/api/auth/status')).json();
  const launch=await (await page.request.post(seed.origin+'/api/editors/wordcraft',{headers:{Origin:seed.origin,'X-CSRF-Token':auth.csrf}})).json();
  const probe=await page.context().newPage();await probe.goto(seed.editorOrigin+'/healthz');
  const result=await probe.evaluate(async url=>{
   const {clearEditorIdentity}=await import(url.replace('/index.html','/__liberty/editor-storage.mjs'));
   const root=await navigator.storage.getDirectory();
   const file=await root.getFileHandle('previous-account.txt',{create:true});const writable=await file.createWritable();await writable.write('previous account private document');await writable.close();
   localStorage.setItem('liberty.identity','previous-account');localStorage.setItem('liberty.opfs.identity','previous-account');
   await clearEditorIdentity('new-account',{local:localStorage,session:sessionStorage,indexed:indexedDB,filesystem:navigator.storage,caches:window.caches,locks:navigator.locks});
   return {names:await Array.fromAsync(root.keys()),identity:localStorage.getItem('liberty.identity')};
  },launch.url);
  expect(result.names).toEqual([]);expect(result.identity).toBe('new-account');await probe.close();
  await page.request.delete(seed.origin+'/api/editors/'+launch.ticket_id,{headers:{Origin:seed.origin,'X-CSRF-Token':auth.csrf}});
 });
});
