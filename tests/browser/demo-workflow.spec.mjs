import {test,expect} from '@playwright/test';
const origin=process.env.LIBERTY_DEMO_ORIGIN;
if(!origin)throw Error('Set an explicit isolated demo portal.');
const privacy={
 en:'Files are processed in your browser and are not uploaded to our server. Demo work is temporary. Download a copy, then use Finish and clear to remove local demo data. If the browser closes unexpectedly, local data may remain until your next visit or manual removal of this site\'s data.',
 'pt-BR':'Os arquivos são processados no navegador e não são enviados ao nosso servidor. O trabalho da demo é temporário. Baixe uma cópia e use Concluir e limpar para apagar os dados locais da demo. Se o navegador fechar inesperadamente, dados locais podem permanecer até a próxima visita ou a remoção dos dados deste site.'
};
async function launch(page,language='en'){
 await page.route('**/demo/apps',async route=>{
  const response=await route.fetch(),catalog=await response.json();
  for(const app of catalog.apps)if(app.id==='wordcraft')app.url+='?light';
  await route.fulfill({response,json:catalog});
 });
 await page.goto(origin+'/demo?lang='+language);
}
async function openLight(page){
 await page.locator('.app-card[title="WordCraft"]').click();
 await expect(page.frameLocator('#demo-frame iframe').locator('.light-document')).toBeVisible();
 return page.frames().find(frame=>frame.url().includes('/demo/runtime/wordcraft/'));
}
async function choose(page,frame,name,content){
 const pending=page.waitForEvent('filechooser');await frame.locator('.light-toolbar button').filter({hasText:/Open TXT\/HTML|Abrir TXT\/HTML/}).click();
 await(await pending).setFiles({name,mimeType:'text/plain',buffer:Buffer.from(content)});
}
async function finish(page){
 page.once('dialog',dialog=>dialog.accept());await page.locator('#demo-close').click();await expect(page.locator('#demo-launcher')).toBeVisible();
}
for(const language of ['en','pt-BR'])for(const width of [320,390,780,1280])test(`persistent ${language} demo workflow fits ${width}px and focus/fullscreen`,async({page},info)=>{
 await page.setViewportSize({width,height:1000});await launch(page,language);
 await expect(page.locator('html')).toHaveAttribute('lang',language);
 await expect(page.locator('#demo-privacy')).toHaveText(privacy[language]);await expect(page.locator('#demo-privacy')).toBeVisible();
 const light=await openLight(page);
 await expect(page.locator('#demo-close')).toHaveText(language==='en'?'Finish and clear':'Concluir e limpar');
 await expect(page.locator('#demo-budget')).toHaveAttribute('data-files','0');await expect(page.locator('#demo-budget')).toHaveAttribute('data-bytes','0');
 await expect(page.locator('#demo-format')).toContainText('2 MiB');await expect(page.locator('#demo-guide')).toBeVisible();
 await expect(page.locator('#demo-privacy')).toHaveText(privacy[language]);
 expect(await page.evaluate(()=>innerWidth)).toBe(width);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 const frame=await page.locator('#demo-frame iframe').boundingBox();expect(frame.x).toBeGreaterThanOrEqual(0);expect(frame.x+frame.width).toBeLessThanOrEqual(width+1);expect(frame.height).toBeGreaterThan(160);
 await expect(page.locator('#demo-status')).toHaveAttribute('aria-live','polite');
 expect(await light.evaluate(()=>Array.from(document.querySelectorAll('.light-toolbar button')).every(button=>{
  const box=button.getBoundingClientRect(),x=box.x+box.width/2,y=box.y+box.height/2;
  return box.x>=0&&box.right<=innerWidth&&document.elementFromPoint(x,y)?.closest('button')===button;
 }))).toBe(true);
 await page.getByRole('button',{name:language==='en'?'Focus mode':'Modo foco',exact:true}).click();
 await expect(page.locator('#demo-privacy')).toBeVisible();
 expect((await page.locator('#demo-privacy').boundingBox()).y).toBeGreaterThanOrEqual(0);
  await page.getByRole('button',{name:language==='en'?'Exit focus':'Sair do foco',exact:true}).click();
 if(width===1280){
  await page.getByRole('button',{name:language==='en'?'Full screen':'Tela cheia',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>document.fullscreenElement?.id)).toBe('demo-editor');await expect(page.locator('#demo-privacy')).toBeVisible();
  await page.getByRole('button',{name:language==='en'?'Exit full screen':'Sair da tela cheia',exact:true}).click();
 }
 await page.screenshot({path:info.outputPath('workflow.png')});await finish(page);await expect(page.locator('#demo-privacy')).toBeVisible();
});

test('locale switching preserves the imported document, filename and cumulative budget',async({page})=>{
 await launch(page);const frame=await openLight(page);await choose(page,frame,'locale.txt','Local locale fixture');
 await expect(frame.locator('.light-document')).toHaveText('Local locale fixture');
 await frame.locator('.light-heading input').fill('keep-this-name.txt');
 await expect(page.locator('#demo-budget')).toHaveAttribute('data-files','1');
 await page.getByRole('combobox',{name:'Language / Idioma'}).selectOption('pt-BR');
 await expect(page.locator('#demo-privacy')).toHaveText(privacy['pt-BR']);await expect(frame.locator('.light-heading input')).toHaveValue('keep-this-name.txt');
 await expect(frame.locator('.light-document')).toHaveText('Local locale fixture');await expect(page.locator('#demo-budget')).toHaveAttribute('data-files','1');
 await choose(page,frame,'unsupported.docx','Not a document');await expect(frame.locator('.light-status')).toContainText('formato');
 await expect(frame.locator('.light-document')).toHaveText('Local locale fixture');await expect(page.locator('#demo-budget')).toHaveAttribute('data-files','1');
 await finish(page);await expect(page.locator('#demo-message')).toContainText('apagados');
});

test('failed cleanup keeps the selected budget visible until confirmed clearing',async({page})=>{
 await launch(page);const frame=await openLight(page);await choose(page,frame,'cleanup.txt','Keep this until cleanup');
 await expect(page.locator('#demo-budget')).toHaveAttribute('data-files','1');
 const controller=page.frames().find(frame=>frame.url().includes('/demo/controller#'));
 await controller.evaluate(()=>{window.__opfs=navigator.storage.getDirectory.bind(navigator.storage);navigator.storage.getDirectory=async()=>{throw Error('Synthetic cleanup failure')}});
 page.once('dialog',dialog=>dialog.accept());await page.locator('#demo-close').click();
 await expect(page.locator('#demo-status')).toContainText('not complete');await expect(page.locator('#demo-budget')).toHaveAttribute('data-files','1');
 await expect(page.locator('#demo-close')).toBeEnabled();await expect(page.locator('#demo-privacy')).toBeVisible();
 await controller.evaluate(()=>{navigator.storage.getDirectory=window.__opfs});await finish(page);
});

test('budget and mode notifications require the active engine, origin, nonce and exact shape',async({page})=>{
 await launch(page);await openLight(page);
 await page.evaluate(()=>{
  const engine=document.querySelector('#demo-frame iframe'),controller=document.querySelector('iframe[name="liberty-demo-controller"]'),url=new URL(engine.src);
  const data={type:'liberty.demo.budget',nonce:url.hash.slice(1),files:9,bytes:90};
  for(const change of [{source:controller.contentWindow},{origin:'https://untrusted.invalid'},{data:{...data,nonce:'x'.repeat(32)}},
   {data:{...data,files:-1}},{data:{...data,bytes:100_000_001}},{data:{...data,filename:'not-allowed.txt'}}]){
   dispatchEvent(new MessageEvent('message',{source:engine.contentWindow,origin:url.origin,data,...change}));
  }
  dispatchEvent(new MessageEvent('message',{source:controller.contentWindow,origin:url.origin,data:{type:'liberty.demo.policy',nonce:url.hash.slice(1),light:false}}));
 });
 await expect(page.locator('#demo-budget')).toHaveAttribute('data-files','0');await expect(page.locator('#demo-format')).toContainText('.html');await finish(page);
});

test('keyboard users can change view and finish without losing the privacy notice',async({page})=>{
 await page.setViewportSize({width:390,height:1000});await launch(page);await openLight(page);
 await expect(page.locator('#demo-close')).toBeFocused();await page.keyboard.press('Tab');
 await expect(page.getByRole('button',{name:'Focus mode',exact:true})).toBeFocused();await page.keyboard.press('Space');
 await expect(page.locator('#demo-privacy')).toBeVisible();await expect(page.locator('#demo-status')).toBeVisible();
 await page.keyboard.press('Space');await page.locator('#demo-close').focus();page.once('dialog',dialog=>dialog.accept());
 await page.keyboard.press('Enter');await expect(page.locator('#demo-launcher')).toBeVisible();
 await expect(page.locator('#demo-apps button').first()).toBeFocused();
});
