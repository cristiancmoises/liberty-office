import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';

const origin=process.env.LIBERTY_DEMO_ORIGIN||'http://localhost:8097';
const lock=JSON.parse(readFileSync(new URL('../../branding.lock.json',import.meta.url)));

for(const spec of lock.apps.filter(app=>app.patches.some(patch=>patch.kind!=='text-label'))){
 test(`${spec.id}: pinned modified WASM runs and replacement graphics decode`,async({page},info)=>{
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(origin+'/demo');
  const catalog=await (await page.request.get(origin+'/demo/apps')).json();
  const app=catalog.apps.find(app=>app.id===spec.id);
  await page.locator('.app-card').filter({hasText:app.name}).click();
  const frame=page.frameLocator('#demo-frame iframe');
  await expect(frame.locator('html')).toHaveAttribute('data-liberty-state','ready',{timeout:180000});
  await expect(frame.locator('canvas')).toBeVisible();
  const runtime=page.frames().find(frame=>frame.url().includes('/demo/runtime/'+spec.id+'/'));
  const result=await runtime.evaluate(async spec=>{
   const response=await fetch('./'+spec.wasm_file);
   if(!response.ok)throw new Error('WASM fetch failed: '+response.status);
   const bytes=new Uint8Array(await response.arrayBuffer());
   const hex=bytes=>Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
   const hash=async bytes=>hex(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)));
   const graphics=[];
   for(const patch of spec.patches){
    const data=bytes.slice(patch.offset,patch.offset+patch.length);
    const item={kind:patch.kind,hash:await hash(data)};
    if(patch.kind==='path-mark'){
     const canvas=document.createElement('canvas');canvas.width=128;canvas.height=128;
     const context=canvas.getContext('2d');context.fill(new Path2D(new TextDecoder().decode(data)));
     item.visible=Array.from(context.getImageData(0,0,128,128).data).some(value=>value!==0);
    }else if(patch.kind!=='text-label'){
     const type=patch.kind.startsWith('png-')?'image/png':'image/svg+xml';
     const url=URL.createObjectURL(new Blob([data],{type}));
     try{
      const image=new Image();image.src=url;await image.decode();
      const canvas=document.createElement('canvas');canvas.width=128;canvas.height=128;
      const context=canvas.getContext('2d');context.drawImage(image,0,0,128,128);
      item.visible=Array.from(context.getImageData(0,0,128,128).data).some(value=>value!==0);
      item.width=image.naturalWidth;item.height=image.naturalHeight;
     }finally{URL.revokeObjectURL(url)}
    }
    graphics.push(item);
   }
   return {hash:await hash(bytes),valid:WebAssembly.validate(bytes),graphics};
  },spec);
  expect(result.hash).toBe(spec.modified_sha256);expect(result.valid).toBe(true);
  result.graphics.forEach((item,index)=>{
   expect(item.hash).toBe(spec.patches[index].replacement_sha256);
   if(item.kind!=='text-label')expect(item.visible).toBe(true);
  });
  await info.attach('verified-branding.json',{body:JSON.stringify(result,null,2),contentType:'application/json'});
  if(spec.id==='filmcraft'){
   // Native canvas Help → About exposes the Rust PNG decoder and the neutral label.
   await frame.locator('canvas').click({position:{x:688,y:20}});
   await page.waitForTimeout(150);
   await frame.locator('canvas').click({position:{x:730,y:216}});
   await page.waitForTimeout(300);
  }
  await page.screenshot({path:info.outputPath(spec.id+'-independent-branding.png')});
 });
}
