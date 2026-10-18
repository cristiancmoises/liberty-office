import {test,expect} from '@playwright/test';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';

// Legacy EffectCraft worker, version 42c57770a76562be, from the pinned
// MIT OR Apache-2.0 bundle recorded in docs/LICENSING.md. Precached resources are
// inert synthetic responses: this tests real worker/cache lifecycle, not WASM.
const worker=await readFile(new URL('../fixtures/effectcraft-42c57770a76562be-sw.js',import.meta.url));
const session=await readFile(new URL('../../liberty/static/demo-session.mjs',import.meta.url));
let server,origin,generation;
test.beforeEach(async()=>{
 generation='LEGACY';
 server=createServer((request,response)=>{
  const path=new URL(request.url,'http://localhost').pathname;
  response.setHeader('Cache-Control','no-store');
  if(path.endsWith('/sw.js')){response.setHeader('Content-Type','text/javascript');response.end(worker)}
  else if(path==='/demo-session.mjs'){response.setHeader('Content-Type','text/javascript');response.end(session)}
  else if(path==='/harness'||path.endsWith('/')||path.endsWith('/index.html')){
   response.setHeader('Content-Type','text/html');response.end('<!doctype html><title>Worker fixture</title><p>'+generation+'</p>');
  }else{response.setHeader('Content-Type','application/octet-stream');response.end('inert precache fixture')}
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin='http://127.0.0.1:'+server.address().port;
});
test.afterEach(async()=>{await new Promise(resolve=>server.close(resolve))});

test('legacy Effect worker blocks cleanup until its controlled page closes',async({page,context})=>{
 await page.goto(origin+'/harness');
 await page.evaluate(async()=>{
  const registration=await navigator.serviceWorker.register('/demo/runtime/effectcraft/sw.js');
  const worker=registration.installing||registration.waiting||registration.active;
  if(worker.state!=='activated')await new Promise(resolve=>worker.addEventListener('statechange',()=>{if(worker.state==='activated')resolve()}));
  window.__legacyWorker=worker;
 });
 const legacy=await context.newPage();await legacy.goto(origin+'/demo/runtime/effectcraft/');
 await expect.poll(()=>legacy.evaluate(()=>!!navigator.serviceWorker.controller)).toBe(true);
 generation='CANDIDATE';await legacy.goto(origin+'/demo/runtime/effectcraft/?new-version=1');
 await expect(legacy.locator('p')).toHaveText('LEGACY');
 await page.evaluate(()=>{
  localStorage.setItem('legacy-document','do not clear while the client survives');window.__state='pending';
  import('/demo-session.mjs').then(module=>module.acquireDemoSession(window,{portalOrigin:'https://portal.example',nonce:'legacy-worker-qualification-00001'}))
   .then(session=>{window.__session=session;window.__state='ready'},error=>{window.__state=error.message});
 });
 await expect.poll(()=>page.evaluate(()=>localStorage.getItem('liberty.demo.retiring-workers'))).toBe('1');
 expect(await page.evaluate(()=>window.__state)).toBe('pending');
 expect(await page.evaluate(()=>localStorage.getItem('legacy-document'))).toBe('do not clear while the client survives');
 expect(await page.evaluate(async()=>(await caches.keys()).includes('effectcraft-42c57770a76562be'))).toBe(true);
 await legacy.close();await expect.poll(()=>page.evaluate(()=>window.__state),{timeout:15000}).toBe('ready');
 expect(await page.evaluate(()=>window.__legacyWorker.state)).toBe('redundant');
 expect(await page.evaluate(async()=>({registrations:(await navigator.serviceWorker.getRegistrations()).length,caches:await caches.keys(),document:localStorage.getItem('legacy-document')})))
  .toEqual({registrations:0,caches:[],document:null});
 const next=await context.newPage();await next.goto(origin+'/demo/runtime/effectcraft/?new-version=2');await expect(next.locator('p')).toHaveText('CANDIDATE');
 expect(await next.evaluate(()=>navigator.serviceWorker.controller)).toBe(null);await next.close();
 await page.evaluate(async()=>{await window.__session.finish();window.__session.dispose()});
 await expect.poll(()=>page.evaluate(async()=>(await navigator.locks.query()).held.length)).toBe(0);
});
