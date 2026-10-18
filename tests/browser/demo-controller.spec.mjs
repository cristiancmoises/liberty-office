import {test,expect} from '@playwright/test';

const origin=process.env.LIBERTY_DEMO_ORIGIN,editorOrigin=process.env.LIBERTY_TEST_EDITOR_ORIGIN;
if(!origin||!editorOrigin)throw Error('Set explicit isolated portal and private editor origins.');

async function controller(page,demoOrigin,name){
 await page.evaluate(({demoOrigin,name})=>{
  const frame=document.createElement('iframe');frame.name=name;frame.id=name;frame.hidden=true;
  frame.sandbox='allow-scripts allow-same-origin';frame.src=demoOrigin+'/demo/controller#'+crypto.randomUUID();document.body.append(frame);
 },{demoOrigin,name});
 await expect.poll(()=>page.frames().find(frame=>frame.name()===name)?.url()).toContain('/demo/controller#');
 const frame=page.frame({name});await frame.waitForLoadState('load');return frame;
}
async function send(page,name,action){
 return page.evaluate(({name,action})=>new Promise((resolve,reject)=>{
  const frame=document.getElementById(name),url=new URL(frame.src),nonce=url.hash.slice(1);
  const requestId='request-'+String(window.__demoRequest=(window.__demoRequest||0)+1).padStart(8,'0');
  const timer=setTimeout(()=>{removeEventListener('message',reply);reject(Error('Controller did not complete the requested operation.'))},15000);
  function reply(event){
   if(event.source!==frame.contentWindow||event.origin!==url.origin||event.data?.type!=='liberty.demo.session'||event.data.nonce!==nonce||event.data.requestId!==requestId)return;
   clearTimeout(timer);removeEventListener('message',reply);resolve(event.data.status);
  }
  addEventListener('message',reply);frame.contentWindow.postMessage({type:'liberty.demo.session',nonce,requestId,action},url.origin);
 }),{name,action});
}

test('real demo controllers retain ownership through blocked deletion and preserve private-origin storage',async({page})=>{
 await page.goto(origin+'/demo');
 const catalog=await (await page.request.get(origin+'/demo/apps')).json(),demoOrigin=new URL(catalog.apps[0].url).origin;
 await page.evaluate(editorOrigin=>{
  const frame=document.createElement('iframe');frame.name='private-sentinel';frame.src=editorOrigin+'/healthz';frame.hidden=true;document.body.append(frame);
 },editorOrigin);
 await expect.poll(()=>page.frames().find(frame=>frame.name()==='private-sentinel')?.url()).toBe(editorOrigin+'/healthz');
 const privateFrame=page.frame({name:'private-sentinel'});await privateFrame.waitForLoadState('load');
 await privateFrame.evaluate(async()=>{
  localStorage.setItem('private-sentinel','unchanged');
  const root=await navigator.storage.getDirectory(),file=await root.getFileHandle('private-sentinel.txt',{create:true}),stream=await file.createWritable();
  await stream.write('private origin fixture');await stream.close();
 });
 const first=await controller(page,demoOrigin,'owner-a');
 expect(await send(page,'owner-a','acquire')).toBe('ready');
 await first.evaluate(async()=>{
  localStorage.setItem('project','active work');
  const root=await navigator.storage.getDirectory(),file=await root.getFileHandle('demo-fixture.txt',{create:true}),stream=await file.createWritable();
  await stream.write('temporary demo fixture');await stream.close();
  await new Promise((resolve,reject)=>{
   const request=indexedDB.open('held-demo-fixture',1);
   request.onerror=()=>reject(request.error);request.onsuccess=()=>{
    window.__heldDemoDb=request.result;window.__heldDemoDb.onversionchange=()=>{window.__demoDeleteStarted=true};resolve();
   };
  });
 });
 await controller(page,demoOrigin,'owner-b');expect(await send(page,'owner-b','acquire')).toBe('busy');
 expect(await first.evaluate(()=>localStorage.getItem('project'))).toBe('active work');
 let completed=false;const clearing=send(page,'owner-a','clear').then(status=>{completed=true;return status});
 await expect.poll(()=>first.evaluate(()=>!!window.__demoDeleteStarted)).toBe(true);
 expect(completed).toBe(false);
 await controller(page,demoOrigin,'owner-c');expect(await send(page,'owner-c','acquire')).toBe('busy');
 await first.evaluate(()=>window.__heldDemoDb.close());expect(await clearing).toBe('cleared');
 expect(await first.evaluate(async()=>({
  local:localStorage.length,databases:(await indexedDB.databases()).length,caches:(await caches.keys()).length,
  files:await Array.fromAsync((await navigator.storage.getDirectory()).keys()),
  owners:(await navigator.locks.query()).held.filter(lock=>lock.name==='liberty.demo.owner').length
 }))).toEqual({local:0,databases:0,caches:0,files:[],owners:1});
 expect(await privateFrame.evaluate(async()=>({
  local:localStorage.getItem('private-sentinel'),
  file:await(await(await(await navigator.storage.getDirectory()).getFileHandle('private-sentinel.txt')).getFile()).text()
 }))).toEqual({local:'unchanged',file:'private origin fixture'});
 expect(await send(page,'owner-a','release')).toBe('cleared');
 await controller(page,demoOrigin,'owner-d');expect(await send(page,'owner-d','acquire')).toBe('ready');
 expect(await send(page,'owner-d','clear')).toBe('cleared');expect(await send(page,'owner-d','release')).toBe('cleared');
});
