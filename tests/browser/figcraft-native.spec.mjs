import {test,expect} from '@playwright/test';
import {readFile,writeFile,chmod} from 'node:fs/promises';
import {createHmac} from 'node:crypto';
import {execFileSync} from 'node:child_process';

const origin=process.env.LIBERTY_DEMO_ORIGIN||'http://localhost:8097';
test.use({viewport:{width:1440,height:1000},deviceScaleFactor:1});

test('FigCraft saves its actual native rectangle and exports a PNG; demo import remains blocked',async({page},info)=>{
 const privateRequests=[];let fileChoosers=0;
 page.on('request',request=>{if(/\/api\//.test(request.url()))privateRequests.push(request.url())});
 page.on('filechooser',()=>fileChoosers++);
 await page.goto(origin+'/demo?lang=en');
 await page.locator('.app-card[title="FigCraft"]').click();
 const frame=page.frameLocator('#demo-frame iframe');
 await expect(frame.locator('html')).toHaveAttribute('data-liberty-state','ready',{timeout:150000});
 const canvas=frame.locator('canvas').first();
 await canvas.click({position:{x:500,y:350}});await page.waitForTimeout(700);
 await page.keyboard.press('r');await page.waitForTimeout(600);
 const box=await canvas.boundingBox();expect(box).not.toBeNull();
 await page.mouse.move(box.x+450,box.y+300);await page.mouse.down();
 await page.mouse.move(box.x+650,box.y+430,{steps:15});await page.mouse.up();
 await page.waitForTimeout(800);await page.keyboard.press('Escape');
 let pending=page.waitForEvent('download');await page.keyboard.press('Control+s');
 const native=await pending;expect(native.suggestedFilename()).toMatch(/\.figcraft$/);
 const project=info.outputPath('rectangle.figcraft');await native.saveAs(project);
 const serialized=execFileSync('python3',['-c','import sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); assert z.testzip() is None; sys.stdout.buffer.write(z.read("document.json"))',project],{encoding:'utf8',maxBuffer:8*1024*1024});
 const document=JSON.parse(serialized);
 expect(Object.values(document.nodes).filter(node=>node.type==='rectangle').map(({width,height})=>({width,height}))).toEqual([{width:200,height:130}]);
 pending=page.waitForEvent('download');
 await canvas.click({position:{x:1320,y:461}});
 const image=await pending;expect(image.suggestedFilename()).toMatch(/\.png$/);
 const png=info.outputPath('rectangle.png');await image.saveAs(png);
 const bytes=await readFile(png);expect(bytes.subarray(0,8).toString('hex')).toBe('89504e470d0a1a0a');
 expect(bytes.readUInt32BE(16)).toBeGreaterThan(0);expect(bytes.readUInt32BE(20)).toBeGreaterThan(0);
 await page.keyboard.press('Control+o');
 await expect(page.locator('#demo-status')).toContainText(/import.*disabled/i);
 expect(fileChoosers).toBe(0);expect(privateRequests).toEqual([]);
 await page.screenshot({path:info.outputPath('figcraft-native.png')});
});

function totp(secret){let bits='';for(const c of secret.toUpperCase())bits+='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'.indexOf(c).toString(2).padStart(5,'0');const key=Buffer.from(bits.match(/.{8}/g).map(b=>parseInt(b,2))),counter=Buffer.alloc(8);counter.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));const hash=createHmac('sha1',key).update(counter).digest(),offset=hash[19]&15;return String((hash.readUInt32BE(offset)&0x7fffffff)%1e6).padStart(6,'0')}

test('FigCraft reopens a real native project from the isolated account Drive and exports SVG',async({page},info)=>{
 const seedPath=process.env.LIBERTY_ACCEPTANCE_SEED;
 const fixtureId=process.env.LIBERTY_FIGCRAFT_FILE_ID;
 test.skip(!seedPath||!fixtureId,'Requires an isolated acceptance account and an existing native FigCraft fixture ID.');
 const seed=JSON.parse(await readFile(seedPath,'utf8'));expect(seed.origin).toBe(origin);
 await page.goto(seed.origin+'/?lang=pt-BR');
 await page.getByLabel('Usuário',{exact:true}).fill(seed.username);await page.getByLabel('Senha',{exact:true}).fill(seed.password);await page.getByRole('button',{name:'Continuar',exact:true}).click();
 await page.getByLabel('Código MFA ou recuperação').fill(seed.recovery);await page.getByRole('button',{name:'Entrar com segurança'}).click();
 await expect(page.locator('.secret')).toBeVisible();const secret=await page.locator('.secret').textContent();
 await page.getByLabel('Código de 6 dígitos').fill(totp(secret));await page.getByRole('button',{name:'Ativar e entrar'}).click();
 seed.recovery=await page.locator('.recovery-codes code').first().textContent();await writeFile(seedPath,JSON.stringify(seed),{mode:0o600});await chmod(seedPath,0o600);
 await page.getByRole('button',{name:'Guardei os códigos. Abrir meu espaço'}).click();await expect(page.locator('#workspace')).toBeVisible();
 await page.getByRole('button',{name:'Aplicativos',exact:true}).click();await page.locator('.app-card').filter({hasText:'FigCraft'}).first().click();
 const frame=page.frameLocator('.editor iframe');await expect(frame.locator('html')).toHaveAttribute('data-liberty-state','ready');const canvas=frame.locator('canvas').first();
 await canvas.click({position:{x:500,y:350}});await page.waitForTimeout(700);
 const files=(await(await page.request.get(seed.origin+'/api/files')).json()).files;
 const created=files.find(file=>file.id===fixtureId);expect(created).toBeTruthy();expect(created.name).toMatch(/\.figcraft$/);
 const initial=await(await page.request.get(seed.origin+'/api/files/'+created.id+'/content')).body();
 const initialPath=info.outputPath('drive-initial.figcraft');await writeFile(initialPath,initial);
 const parse=path=>JSON.parse(execFileSync('python3',['-c','import sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); assert z.testzip() is None; sys.stdout.buffer.write(z.read("document.json"))',path],{encoding:'utf8'}));
 const expected=parse(initialPath);expect(Object.values(expected.nodes).some(node=>node.type==='rectangle'&&node.width===200&&node.height===130)).toBe(true);
 // The owned file is offered through the real portal bridge, never a mocked picker.
 await page.getByRole('button',{name:'Carregar do Drive',exact:true}).click();
 await page.getByRole('dialog').getByRole('button',{name:created.name,exact:true}).click();
 await expect(page.locator('.editor-status')).toContainText('Arquivo oferecido');
 await canvas.click({position:{x:30,y:20}});await page.waitForTimeout(300);
 await canvas.click({position:{x:690,y:147}});await page.waitForTimeout(800);
 const saved=page.waitForResponse(r=>r.url()===seed.origin+'/api/files/'+created.id+'/content'&&r.request().method()==='PUT');
 await page.keyboard.press('Control+s');expect((await saved).ok()).toBe(true);
 const reopenedPath=info.outputPath('drive-reopened.figcraft');await writeFile(reopenedPath,await(await page.request.get(seed.origin+'/api/files/'+created.id+'/content')).body());expect(parse(reopenedPath)).toEqual(expected);
 // Reopened documents center their existing content. Select that native shape.
 await canvas.click({position:{x:750,y:470}});await page.keyboard.press('Control+Shift+e');await page.waitForTimeout(300);
 const downloading=page.waitForEvent('download');await canvas.click({position:{x:590,y:439}});
 const svg=await downloading;expect(svg.suggestedFilename()).toMatch(/\.svg$/);const svgPath=info.outputPath('rectangle.svg');await svg.saveAs(svgPath);
 const shape=execFileSync('python3',['-c','import json,sys,xml.etree.ElementTree as E; r=E.parse(sys.argv[1]).getroot(); print(json.dumps({"tag":r.tag,"width":r.get("width"),"height":r.get("height"),"paths":[p.get("d") for p in r.iter("{http://www.w3.org/2000/svg}path")]}))',svgPath],{encoding:'utf8'});
 expect(JSON.parse(shape)).toEqual({tag:'{http://www.w3.org/2000/svg}svg',width:'200',height:'130',paths:['M0 0L200 0L200 130L0 130Z']});
 await page.screenshot({path:info.outputPath('figcraft-private-restored.png')});
});
