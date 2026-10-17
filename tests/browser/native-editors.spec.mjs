import {test,expect} from '@playwright/test';
import {open as openFile,readFile,stat} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {inflateSync} from 'node:zlib';

const origin=process.env.LIBERTY_DEMO_ORIGIN||'http://localhost:8097';
test.use({viewport:{width:1440,height:1000},deviceScaleFactor:1});
const observations=new WeakMap();
test.beforeEach(async({page})=>{
 const observed={downloads:0,apiRequests:[]};observations.set(page,observed);
 page.on('download',()=>observed.downloads++);
 page.on('request',request=>{const path=new URL(request.url()).pathname;if(path.startsWith('/api/'))observed.apiRequests.push({method:request.method(),path})});
});
test.afterEach(async({page},info)=>{
 await page.waitForTimeout(300);
 const observed=observations.get(page);
 await info.attach('download-boundary',{body:JSON.stringify(observed),contentType:'application/json'});
 expect(observed.apiRequests).toEqual([]);
 expect(observed.downloads).toBe(1);
});

// Coordinates refer to the pinned native canvas UI, not the surrounding portal.
// Only native mouse/keyboard events initiate edits and exports. No fake Blob,
// picker replacement, import-guard bypass, or application command injection.
async function editor(page,name){
 await page.goto(origin+'/demo?lang=en');
 await page.locator(`.app-card[title="${name}"]`).click();
 const frame=page.frameLocator('#demo-frame iframe');
 await expect(frame.locator('html')).toHaveAttribute('data-liberty-state','ready',{timeout:150000});
 const canvas=frame.locator('canvas').first();await expect(canvas).toBeVisible();
 await canvas.click({position:{x:500,y:350}});await page.waitForTimeout(500);
 return canvas;
}
async function drag(page,canvas,from,to){
 const box=await canvas.boundingBox();expect(box).not.toBeNull();
 await page.mouse.move(box.x+from[0],box.y+from[1]);await page.mouse.down();
 await page.mouse.move(box.x+to[0],box.y+to[1],{steps:12});await page.mouse.up();
}
async function downloaded(page,info,action,extension){
 const pending=page.waitForEvent('download',{timeout:60000});await action();
 const download=await pending;
 expect(download.suggestedFilename().toLowerCase()).toMatch(new RegExp('\\.'+extension+'$'));
 const path=info.outputPath(download.suggestedFilename().replace(/[^\w.\-]/g,'_'));
 await download.saveAs(path);expect((await stat(path)).size).toBeGreaterThan(100);
 await page.screenshot({path:info.outputPath('native-export.png')});return path;
}
async function save(page,info,extension){
 return downloaded(page,info,async()=>{await page.keyboard.press('Control+s');await page.waitForTimeout(500);await page.keyboard.press('Enter')},extension);
}
async function header(path,size=32){
 const file=await openFile(path,'r');try{const bytes=Buffer.alloc(size);await file.read(bytes,0,size,0);return bytes}finally{await file.close()}
}
function archive(path,member){
 // Python's standard ZIP reader validates CRCs in bounded chunks; SoundCraft's
 // bundled audio archive is ~66 MiB and is never loaded wholesale into Node.
 return JSON.parse(execFileSync('python3',['-c',
  'import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); assert z.testzip() is None; member=sys.argv[2]; print(json.dumps({"names":z.namelist(),"document":json.loads(z.read(member))}))',
  path,member],{encoding:'utf8',maxBuffer:8*1024*1024}));
}

test('DeckCraft saves its bundled presentation with actual slide data',async({page},info)=>{
 await editor(page,'DeckCraft');const path=await save(page,info,'deckcraft');
 expect((await header(path)).subarray(0,4).toString('hex')).toBe('504b0304');
 const {document}=archive(path,'presentation.json');expect(document.format).toBe('deckcraft');
 expect(document.presentation.slides.length).toBeGreaterThan(0);
});

test('PhotoCraft creates and exports a native PSD document',async({page},info)=>{
 const canvas=await editor(page,'PhotoCraft');
 await page.keyboard.press('Control+n');await page.waitForTimeout(700);
 await page.keyboard.press('Enter');await page.waitForTimeout(1200);
 await page.keyboard.press('b');await drag(page,canvas,[300,300],[450,410]);
 const bytes=await header(await save(page,info,'psd'));
 expect(bytes.subarray(0,4).toString()).toBe('8BPS');expect(bytes.readUInt16BE(4)).toBe(1);
 expect(bytes.readUInt32BE(14)).toBe(1080);expect(bytes.readUInt32BE(18)).toBe(1920);
});

test('VectorCraft exports the rectangle created with the native tool',async({page},info)=>{
 const canvas=await editor(page,'VectorCraft');await canvas.click({position:{x:30,y:159}});
 await drag(page,canvas,[300,300],[450,410]);
 const document=JSON.parse(await readFile(await save(page,info,'vectorcraft'),'utf8'));
 expect(document.format).toBe('vectorcraft');
 expect(document.document.layers.flatMap(layer=>layer.kind.children||[]).some(item=>item.kind?.live?.shape==='rectangle')).toBe(true);
});

test('FilmCraft saves a real bundled editing project',async({page},info)=>{
 await editor(page,'FilmCraft');const project=JSON.parse(await readFile(await save(page,info,'fcproj'),'utf8'));
 expect(project.format).toBe('filmcraft.project');expect(project.schema_version).toBeGreaterThan(0);
 expect(project.project.name).toBe('FilmCraft Demo');
});

test('EffectCraft saves its native composition project',async({page},info)=>{
 await editor(page,'EffectCraft');const project=JSON.parse(await readFile(await save(page,info,'ecproj'),'utf8'));
 expect(project.schema).toBeGreaterThan(0);expect(Object.keys(project.items).length).toBeGreaterThan(0);
 expect(project.openComps.length).toBeGreaterThan(0);
});

test('DesignCraft opens the bundled magazine and saves its native document',async({page},info)=>{
 const canvas=await editor(page,'DesignCraft');await canvas.click({position:{x:300,y:196}});await page.waitForTimeout(1200);
 const {document,names}=archive(await save(page,info,'designcraft'),'document.json');
 expect(names).toContain('mimetype');expect(document.spreads.length).toBeGreaterThan(0);
 expect(Object.keys(document.stories).length).toBeGreaterThan(0);
});

test('SoundCraft exports its sample project and bundled audio as a valid archive',async({page},info)=>{
 await editor(page,'SoundCraft');const {document,names}=archive(await save(page,info,'scraftz'),'Midnight Groove.scraft');
 expect(document.name).toBe('Midnight Groove');expect(document.sample_rate).toBe(48000);
 expect(document.tracks.length).toBeGreaterThan(0);expect(names.some(name=>name.endsWith('.wav'))).toBe(true);
});

test('CADCraft draws a native line and saves DXF entities',async({page},info)=>{
 const canvas=await editor(page,'CADCraft');await canvas.click({position:{x:28,y:182}});
 await canvas.click({position:{x:400,y:300}});await canvas.click({position:{x:600,y:400}});await page.keyboard.press('Escape');
 const drawing=await readFile(await save(page,info,'dxf'),'utf8');
 expect(drawing).toContain('SECTION');expect(drawing).toContain('$ACADVER');
 expect(drawing).toMatch(/\bENTITIES\b/);expect(drawing).toMatch(/\r?\nLINE\r?\n/);expect(drawing.trim()).toMatch(/EOF$/);
});

test('PdfCraft creates a blank page and saves a real PDF',async({page},info)=>{
 const canvas=await editor(page,'PdfCraft');await canvas.click({position:{x:95,y:312}});await page.waitForTimeout(500);
 await canvas.click({position:{x:90,y:423}});await page.waitForTimeout(500);
 const bytes=await readFile(await save(page,info,'pdf')),document=bytes.toString('latin1');
 expect(document).toMatch(/^%PDF-1\.[0-9]/);
 // The pinned exporter stores page dictionaries in a compressed PDF object stream.
 const stream=/\/Type\s*\/ObjStm[\s\S]*?\/Length\s+(\d+)[\s\S]*?stream\r?\n/.exec(document);
 expect(stream).not.toBeNull();const start=stream.index+stream[0].length;
 const objects=inflateSync(bytes.subarray(start,start+Number(stream[1]))).toString('latin1');
 expect(objects).toMatch(/\/Type\s*\/Page\b/);expect(objects).toMatch(/\/Count\s+1\b/);
 expect(document).toContain('%%EOF');expect(document).not.toContain('/JavaScript');
});

test('LightCraft adjusts its sample exposure and exports a full-size PNG',async({page},info)=>{
 const canvas=await editor(page,'LightCraft');await canvas.click({position:{x:1310,y:414}});
 await canvas.click({position:{x:140,y:20}});await page.waitForTimeout(250);
 await canvas.click({position:{x:190,y:525}});await page.waitForTimeout(500);
 await canvas.click({position:{x:586,y:141}});await page.waitForTimeout(500);
 await canvas.click({position:{x:700,y:642}});await page.waitForTimeout(500);
 await page.keyboard.type('exports',{delay:80});
 const path=await downloaded(page,info,()=>canvas.click({position:{x:510,y:777}}),'png');
 const bytes=await header(path);expect(bytes.subarray(0,8).toString('hex')).toBe('89504e470d0a1a0a');
 expect(bytes.subarray(12,16).toString()).toBe('IHDR');expect(bytes.readUInt32BE(16)).toBe(1365);expect(bytes.readUInt32BE(20)).toBe(2048);
});
