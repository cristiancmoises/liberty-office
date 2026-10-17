import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';

const assets=fileURLToPath(new URL('../../liberty/static/',import.meta.url));
const origin='http://light-editor.test';

// Component qualification: real Chromium DOM/native input, synthetic file I/O.
// No account, Drive, production service, or iframe guard is bypassed.
async function boot(page,{language='en',demo=false}={}){
 const unexpected=[];
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url()),name=url.pathname.split('/').at(-1);
  if(url.origin===origin&&url.pathname==='/index.html')return route.fulfill({contentType:'text/html',body:'<!doctype html><html><head></head><body></body></html>'});
  if(url.origin===origin&&['light-editor.mjs','light-editor.css','i18n.mjs','translations.mjs'].includes(name)){
   return route.fulfill({contentType:name.endsWith('.css')?'text/css':'text/javascript',body:await readFile(assets+name)});
  }
  unexpected.push(route.request().url());return route.abort();
 });
 await page.goto(origin+'/index.html?lang='+language);
 await page.evaluate(async demo=>{
  const {mountLightEditor}=await import('/light-editor.mjs');
  window.saved=[];window.delaySave=false;
  window.showOpenFilePicker=async()=>[{getFile:async()=>new File([window.incoming.text],window.incoming.name,{type:window.incoming.type||'text/html'})}];
  mountLightEditor(window,{demo,onState(){},onSave:async(blob,name)=>{
   window.saved.push({name,text:await blob.text()});
   if(window.delaySave)await new Promise(resolve=>{window.finishSave=resolve});
  }});
 },demo);
 return {unexpected,area:page.locator('.light-document'),name:page.locator('.light-heading input'),status:page.locator('.light-status')};
}
async function openFile(page,text,name='fixture.html'){
 await page.evaluate(incoming=>{window.incoming=incoming},{text,name});
 await page.locator('.light-toolbar button').nth(4).click();
}
async function save(page,count=1){
 await page.locator('.light-toolbar button').last().click();
 await page.waitForFunction(count=>window.saved.length===count,count);
 return page.evaluate(()=>window.saved.at(-1));
}

test('HTML saved after native Enter preserves its lines when reopened',async({page})=>{
 const {area}=await boot(page);await area.click();
 await page.keyboard.type('First line');await page.keyboard.press('Enter');await page.keyboard.type('Second line');
 const before=await area.innerText(),saved=await save(page);
 await openFile(page,saved.text,saved.name);
 await expect.poll(()=>area.textContent()).toBe(before);
});

test('HTML imports block, list, table and explicit line boundaries as text',async({page})=>{
 const {area}=await boot(page);
 await openFile(page,'<h1>Heading</h1><p>Paragraph<br>Line</p><ul><li>One</li><li>Two</li></ul><table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>');
 await expect.poll(()=>area.textContent()).toBe('Heading\nParagraph\nLine\nOne\nTwo\nA\tB\nC\tD');
 expect(await area.locator('*').count()).toBe(0);
});

test('HTML parsing never activates markup or fetches resources and skips non-document text',async({page})=>{
 const {area,unexpected}=await boot(page);
 const hostile='<!doctype html><html><head><title>hidden title</title><style>@import "https://leak.test/style";hidden style</style></head><body><p>Safe</p><script>window.htmlExecuted=true</script><img src="https://leak.test/image" onerror="window.htmlExecuted=true"><iframe src="https://leak.test/frame" srcdoc="<script>parent.htmlExecuted=true</script>"></iframe><svg onload="window.htmlExecuted=true"></svg><template>hidden template</template><a href="javascript:window.htmlExecuted=true">Link</a></body></html>';
 await openFile(page,hostile);await expect.poll(()=>area.textContent()).toBe('Safe\nLink');
 const saved=await save(page);await page.waitForTimeout(100);
 expect(await page.evaluate(()=>!!window.htmlExecuted)).toBe(false);
 expect(await area.locator('*').count()).toBe(0);expect(unexpected).toEqual([]);
 expect(saved.text).not.toMatch(/hidden|<script|<img|<iframe|<svg|<template|<a\s|onerror|javascript:/i);
});

test('oversized HTML is rejected before parsing and leaves the current document intact',async({page})=>{
 const {area,status}=await boot(page);await area.fill('Keep this document');
 await page.evaluate(()=>{
  window.parses=0;const descriptor=Object.getOwnPropertyDescriptor(Element.prototype,'innerHTML');
  Object.defineProperty(Element.prototype,'innerHTML',{...descriptor,set(value){window.parses++;descriptor.set.call(this,value)}});
  const parse=DOMParser.prototype.parseFromString;DOMParser.prototype.parseFromString=function(...args){window.parses++;return parse.apply(this,args)};
 });
 await openFile(page,'x'.repeat(2*1024*1024+1));await expect(status).toContainText('2 MiB');
 await expect(area).toHaveText('Keep this document');expect(await page.evaluate(()=>window.parses)).toBe(0);
});

for(const change of ['content','filename','formatting'])test(`save acknowledgement preserves dirty state after ${change} changes`,async({page})=>{
 const {area,name,status}=await boot(page);await area.fill('Saved version');
 await page.evaluate(()=>{window.delaySave=true});await save(page);
 await page.waitForFunction(()=>window.finishSave);
 if(change==='content'){await area.press('End');await area.pressSequentially(' plus unsaved edit')}
 if(change==='filename')await name.fill('renamed.html');
 if(change==='formatting'){await area.press('Control+a');await page.getByRole('button',{name:'Bold',exact:true}).click()}
 await page.evaluate(()=>window.finishSave());await expect(page.locator('.light-toolbar button').last()).toBeEnabled();
 await expect(status).toContainText('Unsaved changes.');
 expect((await page.evaluate(()=>window.saved[0])).text).not.toContain('plus unsaved edit');
});

for(const language of ['en','pt-BR'])test(`plain-text TXT/Markdown warning persists and saves raw text (${language})`,async({page})=>{
 const {area,name,status}=await boot(page,{language});await name.fill('notes.md');
 const warning=page.locator('.light-format-note');
 await expect(warning).toBeVisible();await expect(warning).toContainText(language==='en'?'without formatting':'sem formatação');
 await area.fill('Important');await area.press('Control+a');
 await page.getByRole('button',{name:language==='en'?'Bold':'Negrito',exact:true}).click();
 expect(await area.locator('b,strong').count()).toBeGreaterThan(0);
 const saved=await save(page);expect(saved.text).toBe('Important');expect(saved.name).toBe('notes.md');
 await expect(warning).toBeVisible();await expect(status).toContainText(language==='en'?'plain text':'texto puro');
 await name.fill('notes.txt');await expect(warning).toBeVisible();
 await name.fill('notes.html');await expect(warning).toBeHidden();
});
