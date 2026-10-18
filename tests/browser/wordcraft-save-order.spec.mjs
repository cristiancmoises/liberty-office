import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';

const origin=process.env.LIBERTY_DEMO_ORIGIN;
if(!origin)throw Error('Specify an isolated demo portal.');
test.use({viewport:{width:1440,height:1000},deviceScaleFactor:2});

test('native WordCraft includes queued final text in the same-frame save',async({page,context},info)=>{
 await page.goto(origin+'/demo?lang=en');await page.locator('.app-card[title="WordCraft"]').click();
 const frame=page.frameLocator('#demo-frame iframe');await expect(frame.locator('html')).toHaveAttribute('data-liberty-state','ready');
 const canvas=frame.locator('canvas');await canvas.click({position:{x:310,y:200}});await page.waitForTimeout(500);
 const prefix='Native save ordering fixture';await page.keyboard.type(prefix,{delay:70});
 await canvas.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 await canvas.evaluate(()=>{
  const probe={frame:0,events:[],running:true};window.__wordSaveOrder=probe;
  const next=()=>{if(probe.running){probe.frame++;requestAnimationFrame(next)}};requestAnimationFrame(next);
  const observe=event=>probe.events.push({key:event.key,target:event.target.tagName,trusted:event.isTrusted,frame:probe.frame});
  addEventListener('keydown',observe,true);probe.stop=()=>{probe.running=false;removeEventListener('keydown',observe,true)};
 });
 const cdp=await context.newCDPSession(page),pending=page.waitForEvent('download');
 // Queue actual browser text followed by the native save shortcut, without a
 // render wait, synthetic DOM event or engine injection between the two.
 await Promise.all([
  {type:'keyDown',key:'.',code:'Period',text:'.',unmodifiedText:'.',windowsVirtualKeyCode:190},
  {type:'keyUp',key:'.',code:'Period',windowsVirtualKeyCode:190},
  {type:'keyDown',key:'s',code:'KeyS',modifiers:2,windowsVirtualKeyCode:83},
  {type:'keyUp',key:'s',code:'KeyS',modifiers:2,windowsVirtualKeyCode:83},
 ].map(event=>cdp.send('Input.dispatchKeyEvent',event)));await cdp.detach();
 const download=await pending,path=info.outputPath('save-order.docx');await download.saveAs(path);
 const value=execFileSync('python3',['-c',
  'import sys,zipfile,xml.etree.ElementTree as E; r=E.fromstring(zipfile.ZipFile(sys.argv[1]).read("word/document.xml")); print("".join(n.text or "" for n in r.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")),end="")',path],{encoding:'utf8'});
 const trace=await canvas.evaluate(()=>{const probe=window.__wordSaveOrder;probe.stop();return probe.events});
 await info.attach('native-save-key-events',{body:JSON.stringify(trace),contentType:'application/json'});
 expect(trace.map(event=>event.key)).toEqual(['.','s']);expect(trace.every(event=>event.trusted&&event.target==='INPUT')).toBe(true);
 expect(new Set(trace.map(event=>event.frame)).size,'The regression requires both events in one observed browser frame').toBe(1);
 expect(value).toBe(prefix+'.');
 page.once('dialog',dialog=>dialog.accept());await page.locator('#demo-close').click();await expect(page.locator('#demo-launcher')).toBeVisible();
});
