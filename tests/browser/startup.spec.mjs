import {test,expect} from '@playwright/test';
import {writeFile} from 'node:fs/promises';

const origin=process.env.LIBERTY_DEMO_ORIGIN;
if(!origin)throw Error('Set LIBERTY_DEMO_ORIGIN to the isolated test portal.');

async function observe(page){
 const native=[],errors=[];
 page.on('request',request=>{if(/wordcraft\/.*\.(?:wasm|js)(?:\?|$)/.test(request.url()))native.push(request.url())});
 page.on('pageerror',error=>errors.push(error.message));
 const client=await page.context().newCDPSession(page),urls=new Map(),transfers=[];
 await client.send('Network.enable');
 client.on('Network.requestWillBeSent',event=>urls.set(event.requestId,event.request.url));
 client.on('Network.loadingFinished',event=>{
  const url=urls.get(event.requestId);if(url?.includes('/wordcraft/'))transfers.push({url,bytes:event.encodedDataLength});
 });
 return {native,errors,transfers};
}

async function metrics(info,name,evidence,started,readyMs){
 const path=info.outputPath(name+'.json');
 await writeFile(path,JSON.stringify({...evidence,readyMs,settledMs:Date.now()-started},null,2));
 await info.attach(name,{path,contentType:'application/json'});
}

test('light WordCraft starts without native JS or WASM requests',async({page},info)=>{
 await page.setViewportSize({width:1280,height:900});
 await page.route('**/demo/apps',async route=>{
  const response=await route.fetch(),catalog=await response.json();
  for(const app of catalog.apps)if(app.id==='wordcraft')app.url+='?light';
  await route.fulfill({response,json:catalog});
 });
 const evidence=await observe(page),runs=[];
 for(const phase of ['cold','warm']){
  evidence.native.length=0;evidence.errors.length=0;evidence.transfers.length=0;
  const started=Date.now();
  await page.goto(origin+'/demo');await page.locator('.app-card[title="WordCraft"]').click();
  const editor=page.frameLocator('#demo-frame iframe');
  await expect(editor.locator('.light-document')).toBeVisible();
  const readyMs=Date.now()-started;
  await page.waitForLoadState('networkidle');
  await metrics(info,'light-startup-'+phase,evidence,started,readyMs);
  runs.push({native:[...evidence.native],errors:[...evidence.errors]});
 }
 for(const run of runs){expect(run.native).toEqual([]);expect(run.errors).toEqual([])}
 await expect(page.frameLocator('#demo-frame iframe').locator('head link[data-liberty-rel]')).not.toHaveCount(0);
});

test('full WordCraft restores native preloads and reaches its real runner',async({page},info)=>{
 await page.setViewportSize({width:1440,height:1000});
 const evidence=await observe(page);
 for(const phase of ['cold','warm']){
  evidence.native.length=0;evidence.errors.length=0;evidence.transfers.length=0;
  const started=Date.now();
  await page.goto(origin+'/demo');await page.locator('.app-card[title="WordCraft"]').click();
  const editor=page.frameLocator('#demo-frame iframe');
  await expect(editor.locator('html')).toHaveAttribute('data-liberty-state','ready',{timeout:120000});
  const readyMs=Date.now()-started;
  await expect(editor.locator('canvas').first()).toBeVisible();
  await expect(editor.locator('.light-document')).toHaveCount(0);
  await expect(editor.locator('head link[data-liberty-rel]')).toHaveCount(0);
  expect(evidence.native.some(url=>/\.wasm(?:\?|$)/.test(url))).toBe(true);
  expect(evidence.errors).toEqual([]);
  await page.waitForLoadState('networkidle');
  await metrics(info,'full-startup-'+phase,evidence,started,readyMs);
 }
});

test('warm WordCraft demo reuses public code without reusing runtime configuration',async({playwright},info)=>{
 const context=await playwright.chromium.launchPersistentContext(info.outputPath('browser-profile'),{
  ...info.project.use.launchOptions,headless:true,viewport:{width:1440,height:1000}
 });
 try{
 const page=context.pages()[0];
 const evidence=await observe(page),runs=[];
 for(const phase of ['cold','warm']){
  evidence.native.length=0;evidence.transfers.length=0;evidence.errors.length=0;
  const started=Date.now();
  await page.goto(origin+'/demo');await page.locator('.app-card[title="WordCraft"]').click();
  const editor=page.frameLocator('#demo-frame iframe');
  await expect(editor.locator('html')).toHaveAttribute('data-liberty-state','ready',{timeout:120000});
  const readyMs=Date.now()-started;
  await page.waitForLoadState('networkidle');
  await metrics(info,'cached-startup-'+phase,evidence,started,readyMs);
  const runtime=page.frames().find(frame=>frame.url().includes('/demo/runtime/wordcraft/'));
  const response=await page.request.get(runtime.url());
  expect(response.headers()['cache-control']).toBe('no-store');
  runs.push({native:[...evidence.native],bytes:evidence.transfers
   .filter(item=>item.url.includes('/public-assets/')&&/\.(?:wasm|js)(?:\?|$)/.test(item.url))
   .reduce((total,item)=>total+item.bytes,0)});
 }
 for(const run of runs)expect(run.native.every(url=>url.includes('/public-assets/'))).toBe(true);
 expect(runs[0].bytes).toBeGreaterThan(0);expect(runs[1].bytes).toBe(0);
 expect(evidence.errors).toEqual([]);
 }finally{await context.close()}
});
