import {test,expect} from '@playwright/test';

const origin=process.env.LIBERTY_MAINTENANCE_ORIGIN;
if(!origin)throw Error('Set LIBERTY_MAINTENANCE_ORIGIN to the isolated public-only runtime.');

for(const width of [320,390,780,1280])for(const locale of ['en','pt-BR']){
 test(`public maintenance home at ${width}px in ${locale}`,async({page},info)=>{
  const privateRequests=[],mutations=[],errors=[];
  page.on('request',request=>{
   if(new URL(request.url()).pathname.startsWith('/api/'))privateRequests.push(request.url());
   if(!['GET','HEAD'].includes(request.method()))mutations.push(request.url());
  });
  page.on('pageerror',error=>errors.push(error.message));
  await page.setViewportSize({width,height:900});await page.goto(origin+'/');
  await expect(page.locator('html')).toHaveAttribute('lang','en');
  await expect(page.getByRole('heading',{level:1})).toHaveText('The demo is still available.');
  await page.keyboard.press('Tab');await expect(page.locator('.skip')).toBeFocused();
  await page.keyboard.press('Enter');await expect(page.locator('main')).toBeFocused();
  await page.getByRole('combobox',{name:'Language / Idioma'}).selectOption(locale);
  await expect(page.locator('html')).toHaveAttribute('lang',locale);
  const portuguese=locale==='pt-BR';
  await expect(page.getByRole('heading',{level:1})).toHaveText(portuguese?'A demo continua disponível.':'The demo is still available.');
  await expect(page.getByRole('heading',{level:2})).toHaveText(portuguese?'Manutenção somente das contas':'Account-only maintenance');
  await expect(page.getByRole('note')).toContainText(portuguese?'sem envio ao servidor':'not uploaded to the server');
  await expect(page.locator('input,form')).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const link=page.locator('#try-demo');
  await expect(link).toHaveAttribute('href',origin+'/demo?lang='+locale);
  if(width===390||width===1280)await page.screenshot({path:info.outputPath(`maintenance-${locale}-${width}.png`),fullPage:true});
  await link.click();await expect(page.locator('.app-card')).toHaveCount(13);
  await expect(page.locator('html')).toHaveAttribute('lang',locale);
  expect(privateRequests).toEqual([]);expect(mutations).toEqual([]);expect(errors).toEqual([]);
 });
}

test('public-only runtime still edits and downloads a light document during account maintenance',async({page})=>{
 await page.route('**/demo/apps',async route=>{
  const response=await route.fetch(),catalog=await response.json();
  for(const app of catalog.apps)if(app.id==='wordcraft')app.url+='?light';
  await route.fulfill({response,json:catalog});
 });
 const mutations=[];page.on('request',request=>{if(!['GET','HEAD'].includes(request.method()))mutations.push(request.url())});
 await page.goto(origin+'/demo');await page.locator('.app-card[title="WordCraft"]').click();
 const editor=page.frameLocator('#demo-frame iframe');await expect(editor.locator('.light-document')).toBeVisible();
 await editor.locator('.light-document').fill('A browser-only maintenance document.');
 const pending=page.waitForEvent('download');await editor.getByRole('button',{name:'Download copy',exact:true}).click();
 const download=await pending,stream=await download.createReadStream(),chunks=[];
 for await(const chunk of stream)chunks.push(chunk);
 expect(Buffer.concat(chunks).toString()).toContain('A browser-only maintenance document.');
 page.once('dialog',dialog=>dialog.accept());await page.locator('#demo-close').click();
 await expect(page.locator('#demo-frame iframe')).toHaveCount(0);expect(mutations).toEqual([]);
});
