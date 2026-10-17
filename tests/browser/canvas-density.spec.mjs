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
