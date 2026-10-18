import {test,expect} from '@playwright/test';

const origin=process.env.LIBERTY_DEMO_ORIGIN;
if(!origin)throw Error('Set an explicit isolated demo portal.');
async function light(page){
 await page.route('**/demo/apps',async route=>{
  const response=await route.fetch(),catalog=await response.json();
  for(const app of catalog.apps)if(app.id==='wordcraft')app.url+='?light';
  await route.fulfill({response,json:catalog});
 });
 await page.goto(origin+'/demo');await page.locator('.app-card[title="WordCraft"]').click();
 await expect(page.frameLocator('#demo-frame iframe').locator('.light-document')).toBeVisible();
 return page.frames().find(frame=>frame.url().includes('/demo/runtime/wordcraft/'));
}

test('portal acquires its sibling controller before creating an engine and Finish waits for real cleanup',async({page,context})=>{
 await page.addInitScript(()=>{
  if(window!==top)return;
  window.__readyNonces=new Set();window.__engineAdmission=[];
  addEventListener('message',event=>{if(event.data?.type==='liberty.demo.session'&&event.data.status==='ready')window.__readyNonces.add(event.data.nonce)});
  new MutationObserver(()=>{
   for(const frame of document.querySelectorAll('#demo-frame iframe:not([data-observed])')){
    frame.dataset.observed='true';window.__engineAdmission.push(window.__readyNonces.has(new URL(frame.src).hash.slice(1)));
   }
  }).observe(document,{subtree:true,childList:true});
 });
 const engine=await light(page),controller=page.frames().find(frame=>frame.url().includes('/demo/controller#'));
 expect(controller).toBeTruthy();expect(await page.evaluate(()=>window.__engineAdmission)).toEqual([true]);
 expect(await engine.evaluate(()=>parent===top)).toBe(true);
 await engine.evaluate(async()=>{
  localStorage.setItem('temporary-project','keep until Finish');
  const root=await navigator.storage.getDirectory(),file=await root.getFileHandle('temporary.txt',{create:true}),writer=await file.createWritable();
  await writer.write('temporary fixture');await writer.close();
 });
 const second=await context.newPage();await second.goto(origin+'/demo');await second.locator('.app-card[title="WordCraft"]').click();
 await expect(second.locator('#demo-message')).toContainText('Another demo');
 expect(await second.locator('#demo-frame iframe').count()).toBe(0);
 expect(await engine.evaluate(()=>localStorage.getItem('temporary-project'))).toBe('keep until Finish');
 await second.close();
 // A separate same-origin context deliberately holds an IDB connection open.
 await page.evaluate(demoOrigin=>{
  const frame=document.createElement('iframe');frame.name='deletion-blocker';frame.hidden=true;frame.src=demoOrigin+'/healthz';document.body.append(frame);
 },new URL(engine.url()).origin);
 await expect.poll(()=>page.frame({name:'deletion-blocker'})?.url()).toContain('/healthz');
 const blocker=page.frame({name:'deletion-blocker'});await blocker.waitForLoadState('load');
 await blocker.evaluate(()=>new Promise((resolve,reject)=>{
  const request=indexedDB.open('held-lifecycle',1);request.onerror=()=>reject(request.error);
  request.onsuccess=()=>{window.__db=request.result;window.__db.onversionchange=()=>{window.__blocked=true};resolve()};
 }));
 page.on('dialog',dialog=>dialog.accept());await page.locator('#demo-close').click();
 await expect.poll(()=>blocker.evaluate(()=>!!window.__blocked)).toBe(true);
 expect(await page.locator('#demo-frame iframe').count()).toBe(0);
 await expect(page.locator('#demo-editor')).toBeVisible();
 expect(await controller.evaluate(async()=>(await navigator.locks.query()).held.some(lock=>lock.name==='liberty.demo.owner'))).toBe(true);
 await blocker.evaluate(()=>window.__db.close());await expect(page.locator('#demo-launcher')).toBeVisible();
 expect(await blocker.evaluate(async()=>({local:localStorage.length,databases:(await indexedDB.databases()).length,
  files:await Array.fromAsync((await navigator.storage.getDirectory()).keys()),locks:(await navigator.locks.query()).held.length})))
  .toEqual({local:0,databases:0,files:[],locks:0});
 expect(page.frames().some(frame=>frame.url().includes('/demo/controller#'))).toBe(false);
});

test('reload clears stale demo work before the next native admission',async({page})=>{
 const first=await light(page);await first.evaluate(()=>localStorage.setItem('crashed-project','temporary'));
 await page.reload();await page.locator('.app-card[title="WordCraft"]').click();
 const next=page.frameLocator('#demo-frame iframe');await expect(next.locator('.light-document')).toBeVisible();
 const engine=page.frames().find(frame=>frame.url().includes('/demo/runtime/wordcraft/'));
 expect(await engine.evaluate(()=>localStorage.getItem('crashed-project'))).toBe(null);
});

for(const missing of ['locks','opfs'])test('missing '+missing+' blocks engine creation without unsafe fallback',async({page})=>{
 await page.addInitScript(missing=>{
  if(location.pathname!=='/demo/controller')return;
  if(missing==='locks')Object.defineProperty(navigator,'locks',{value:undefined});
  else Object.defineProperty(navigator,'storage',{value:{}});
 },missing);
 await page.goto(origin+'/demo');await page.locator('.app-card[title="WordCraft"]').click();
 await expect(page.locator('#demo-message')).toContainText('Cannot safely prepare');
 expect(await page.locator('#demo-frame iframe').count()).toBe(0);
});

test('a surviving native engine blocks new ownership after its controller is destroyed',async({page,context})=>{
 const engine=await light(page);await engine.evaluate(()=>localStorage.setItem('surviving-engine','keep'));
 // pagehide may freeze a document rather than destroy it. Only the browser's
 // document cleanup, not this notification, may release the engine lease.
 await engine.evaluate(()=>dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true})));
 await page.evaluate(()=>document.querySelector('iframe[name="liberty-demo-controller"]').remove());
 const second=await context.newPage();await second.goto(origin+'/demo');await second.locator('.app-card[title="WordCraft"]').click();
 await expect(second.locator('#demo-message')).toContainText('Another demo');
 expect(await second.locator('#demo-frame iframe').count()).toBe(0);
 expect(await engine.evaluate(()=>localStorage.getItem('surviving-engine'))).toBe('keep');
 await page.close();await second.locator('.app-card[title="WordCraft"]').click();
 await expect(second.frameLocator('#demo-frame iframe').locator('html')).toHaveAttribute('data-liberty-state','ready',{timeout:120000});
 const fresh=second.frames().find(frame=>frame.url().includes('/demo/runtime/wordcraft/'));
 expect(await fresh.evaluate(()=>localStorage.getItem('surviving-engine'))).toBe(null);
});

test('failed Finish stays blocked until cleanup succeeds and ignores messages from an old engine',async({page,context})=>{
 await light(page);
 await page.evaluate(()=>{window.__oldEngineWindow=document.querySelector('#demo-frame iframe').contentWindow});
 const controller=page.frames().find(frame=>frame.url().includes('/demo/controller#'));
 await controller.evaluate(()=>{
  window.__getDirectory=navigator.storage.getDirectory.bind(navigator.storage);
  navigator.storage.getDirectory=async()=>{throw Error('Synthetic cleanup failure')};
 });
 page.on('dialog',dialog=>dialog.accept());await page.locator('#demo-close').click();
 await expect(page.locator('#demo-status')).toContainText('cleanup is not complete');
 await expect(page.locator('#demo-editor')).toBeVisible();expect(await page.locator('#demo-frame iframe').count()).toBe(0);
 const second=await context.newPage();await second.goto(origin+'/demo');await second.locator('.app-card[title="WordCraft"]').click();
 await expect(second.locator('#demo-message')).toContainText('Another demo');await second.close();
 await controller.evaluate(()=>{navigator.storage.getDirectory=window.__getDirectory});
 await page.locator('#demo-close').click();await expect(page.locator('#demo-launcher')).toBeVisible();
 await page.locator('.app-card[title="WordCraft"]').click();
 await expect(page.frameLocator('#demo-frame iframe').locator('.light-document')).toBeVisible();
 const previous=await page.locator('#demo-status').textContent();let downloads=0;page.on('download',()=>downloads++);
 await page.evaluate(()=>{
  const frame=document.querySelector('#demo-frame iframe'),url=new URL(frame.src);
  dispatchEvent(new MessageEvent('message',{source:window.__oldEngineWindow,origin:url.origin,
   data:{type:'liberty.demo.state',nonce:url.hash.slice(1),text:'Stale engine must not change this project'}}));
  dispatchEvent(new MessageEvent('message',{source:window.__oldEngineWindow,origin:url.origin,
   data:{type:'liberty.demo.export',id:'demo-stale000000',name:'stale.txt',mime:'text/plain',buffer:new TextEncoder().encode('stale').buffer}}));
 });
 expect(await page.locator('#demo-status').textContent()).toBe(previous);expect(downloads).toBe(0);
});
