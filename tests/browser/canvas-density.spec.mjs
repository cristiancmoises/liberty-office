import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
const origin=process.env.LIBERTY_DEMO_ORIGIN||'http://localhost:8097';
test.use({deviceScaleFactor:2});

async function open(page,name){
 await page.goto(origin+'/demo');
 await page.locator('.app-card').filter({hasText:name}).click();
 const editor=page.frameLocator('#demo-frame iframe');
 await expect(editor.locator('html')).toHaveAttribute('data-liberty-state','ready',{timeout:120000});
 return editor;
}

test('all 13 editor canvases fit the viewport at high density and after resizing',async({page})=>{
 test.setTimeout(600000);
 await page.setViewportSize({width:1280,height:900});
 const {apps}=await(await page.request.get(origin+'/demo/apps')).json();
 expect(apps).toHaveLength(13);
 for(const app of apps){
  await test.step(app.name,async()=>{
   const editor=await open(page,app.name);
   for(const width of [1280,780,390]){
    await page.setViewportSize({width,height:900});
    await expect.poll(()=>editor.locator('canvas').first().evaluate(canvas=>{
     const rect=canvas.getBoundingClientRect();
     return Math.abs(canvas.width-rect.width*devicePixelRatio)<=2&&Math.abs(canvas.height-rect.height*devicePixelRatio)<=2;
    })).toBe(true);
    const geometry=await page.locator('#demo-frame iframe').evaluate(frame=>({rect:frame.getBoundingClientRect().toJSON(),width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth}));
    expect(geometry.scrollWidth).toBeLessThanOrEqual(width);
    expect(geometry.rect.right).toBeLessThanOrEqual(width+1);
    expect(geometry.rect.bottom).toBeLessThanOrEqual(geometry.height+1);
   }
   await page.setViewportSize({width:1280,height:900});
  });
 }
});

test('high-density native input reaches WordCraft and GridCraft export contents',async({page},info)=>{
 await page.setViewportSize({width:1440,height:1000});
 let editor=await open(page,'WordCraft');
 await editor.locator('canvas').click({position:{x:310,y:200}});
 await page.waitForTimeout(500);
 await page.keyboard.type('High density native document.',{delay:70});
 let pending=page.waitForEvent('download');await page.keyboard.press('Control+s');
 const docx=info.outputPath('density.docx');await(await pending).saveAs(docx);
 const xml=execFileSync('python3',['-c','import sys,zipfile;sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read("word/document.xml"))',docx],{encoding:'utf8'});
 expect(xml).toContain('High density native document.');
 editor=await open(page,'GridCraft');
 await editor.locator('canvas').click({position:{x:52,y:223}});
 await page.keyboard.type('42',{delay:100});await page.keyboard.press('Enter');
 await page.waitForTimeout(300);
 pending=page.waitForEvent('download');await page.keyboard.press('Control+s');
 const xlsx=info.outputPath('density.xlsx');await(await pending).saveAs(xlsx);
 const sheet=execFileSync('python3',['-c','import sys,zipfile;sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read("xl/worksheets/sheet1.xml"))',xlsx],{encoding:'utf8'});
 expect(sheet).toContain('<v>42</v>');
});

for(const scenario of [
 {name:'Enter commits both digits',keys:['4','2','Enter'],cells:{A1:'42'},selection:'A2'},
 {name:'Tab commits both digits',keys:['4','2','Tab'],cells:{A1:'42'},selection:'B1'},
 {name:'Escape cancels both digits',keys:['4','2','Escape'],cells:{},selection:'A1'},
 {name:'separate commits retain event order',keys:['4','Enter','2','Enter'],cells:{A1:'4',A2:'2'},selection:'A3'},
]){
 test('rapid native GridCraft input: '+scenario.name,async({page,context},info)=>{
  await page.setViewportSize({width:1440,height:1000});
  const editor=await open(page,'GridCraft'),canvas=editor.locator('canvas');
  await canvas.click({position:{x:52,y:223}});
  await expect(canvas).toBeFocused();
  await canvas.evaluate(()=>{
   const probe={frame:0,events:[],running:true};window.__libertyGridRapidProbe=probe;
   const tick=()=>{if(probe.running){probe.frame++;requestAnimationFrame(tick)}};requestAnimationFrame(tick);
   const observe=event=>probe.events.push({key:event.key,trusted:event.isTrusted,target:event.target.tagName,frame:probe.frame,time:performance.now()});
   window.addEventListener('keydown',observe,true);probe.stop=()=>{probe.running=false;window.removeEventListener('keydown',observe,true)};
   return new Promise(resolve=>requestAnimationFrame(resolve));
  });
  // Queue real browser input together. No synthetic DOM events, F2 workaround,
  // engine injection or fixed sleep: the trace below must prove one canvas frame.
  const cdp=await context.newCDPSession(page),events=[];
  for(const key of scenario.keys){
   const code=/^[0-9]$/.test(key)?'Digit'+key:key;
   const virtual=/^[0-9]$/.test(key)?key.charCodeAt(0):{Enter:13,Tab:9,Escape:27}[key];
   events.push({type:'keyDown',key,code,windowsVirtualKeyCode:virtual,...(/^[0-9]$/.test(key)?{text:key,unmodifiedText:key}:{})});
   events.push({type:'keyUp',key,code,windowsVirtualKeyCode:virtual});
  }
  await Promise.all(events.map(event=>cdp.send('Input.dispatchKeyEvent',event)));await cdp.detach();
  const trace=await canvas.evaluate(()=>{const probe=window.__libertyGridRapidProbe;probe.stop();return probe.events});
  await info.attach('rapid-native-key-events',{body:JSON.stringify(trace,null,2),contentType:'application/json'});
  // Allow the native engine to process its queued frame(s), without selecting a
  // different cell or changing the data under test, before requesting export.
  await canvas.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const pending=page.waitForEvent('download');await page.keyboard.press('Control+s');
  const xlsx=info.outputPath('rapid.xlsx');await(await pending).saveAs(xlsx);
  const sheet=JSON.parse(execFileSync('python3',['-c',
   'import json,sys,zipfile,xml.etree.ElementTree as E; root=E.fromstring(zipfile.ZipFile(sys.argv[1]).read("xl/worksheets/sheet1.xml")); ns={"s":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}; selection=root.find("s:sheetViews/s:sheetView/s:selection",ns); print(json.dumps({"cells":{cell.attrib["r"]:cell.find("s:v",ns).text for cell in root.findall("s:sheetData/s:row/s:c",ns) if cell.find("s:v",ns) is not None},"selection":selection.attrib.get("activeCell") if selection is not None else None}))',xlsx],{encoding:'utf8'}));
  expect(trace.map(event=>event.key)).toEqual(scenario.keys);
  expect(trace.every(event=>event.trusted&&event.target==='CANVAS'),'Regression requires trusted events reaching the selected canvas').toBe(true);
  expect(new Set(trace.map(event=>event.frame)).size,'Regression requires one render-frame batch; a split batch is not a passing qualification').toBe(1);
  expect(sheet.cells).toEqual(scenario.cells); // Exact bytes: 4 or duplicated 442 must never pass as 42.
  expect(sheet.selection).toBe(scenario.selection);
 });
}
