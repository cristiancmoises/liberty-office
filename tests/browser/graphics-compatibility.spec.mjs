import {test,expect} from '@playwright/test';
const origin=process.env.LIBERTY_DEMO_ORIGIN;
if(!origin)throw Error('Set LIBERTY_DEMO_ORIGIN to the test portal.');
// Deliberately unavailable graphics, without Playwright's implicit unsafe fallback.
test.use({launchOptions:{...(process.env.LIBERTY_BROWSER_PATH?{executablePath:process.env.LIBERTY_BROWSER_PATH}:{}),chromiumSandbox:true,ignoreDefaultArgs:['--enable-unsafe-swiftshader'],args:['--disable-gpu','--disable-webgl']}});

for(const [language,width] of [['en',1440],['pt-BR',320]]){
 test(`WordCraft never silently substitutes the basic editor without graphics (${language})`,async({page})=>{
  await page.setViewportSize({width,height:900});
  const native=[];page.on('request',request=>{if(/\/public-assets\/[^/]+\/wordcraft\/.*\.(?:js|wasm)(?:\?|$)/.test(request.url()))native.push(request.url())});
  await page.goto(origin+'/demo?lang='+language);
  await page.locator('.app-card[title="WordCraft"]').click();
  const editor=page.frameLocator('#demo-frame iframe');
  await expect(editor.locator('html')).toHaveAttribute('data-liberty-state','blocked',{timeout:15000});
  await expect(editor.locator('.light-document')).toHaveCount(0);
  await expect(editor.getByRole('heading',{level:1})).toBeVisible();
  await expect(editor.locator('.editor-compatibility')).toContainText('chrome://gpu');
  await expect(page.locator('#demo-status')).not.toContainText('did not start');
  await expect(page.locator('#demo-close')).toBeEnabled();
  expect(native).toEqual([]);
  const bounds=await editor.locator('.editor-compatibility').evaluate(node=>({width:innerWidth,scroll:document.documentElement.scrollWidth,buttons:[...node.querySelectorAll('button')].map(b=>b.getBoundingClientRect().toJSON())}));
  expect(bounds.scroll).toBeLessThanOrEqual(bounds.width);
  for(const button of bounds.buttons){expect(button.height).toBeGreaterThanOrEqual(44);expect(button.right).toBeLessThanOrEqual(bounds.width)}
  await editor.getByRole('button',{name:language==='en'?'Open basic text editor':'Abrir editor básico de texto',exact:true}).click();
  await expect(editor.locator('.light-document')).toBeVisible();
  await expect(editor.locator('html')).toHaveAttribute('data-liberty-mode','light');
  expect(native).toEqual([]);
  await editor.locator('.light-document').fill('Explicit basic editor selection.');
  const download=page.waitForEvent('download');
  await editor.getByRole('button',{name:language==='en'?'Download copy':'Baixar cópia',exact:true}).click();
  expect((await download).suggestedFilename()).toBe('document'+(language==='en'?'':'o')+'.html');
 });
}

test('GridCraft explains missing graphics before loading WASM and preserves the full-editor retry',async({page})=>{
 const native=[];page.on('request',request=>{if(/\/public-assets\/[^/]+\/gridcraft\/.*\.(?:js|wasm)(?:\?|$)/.test(request.url()))native.push(request.url())});
 await page.goto(origin+'/demo?lang=en');await page.locator('.app-card[title="GridCraft"]').click();
 const editor=page.frameLocator('#demo-frame iframe');
 await expect(editor.locator('html')).toHaveAttribute('data-liberty-state','blocked',{timeout:15000});
 await expect(editor.getByRole('button',{name:'Open basic text editor',exact:true})).toHaveCount(0);
 expect(native).toEqual([]);
 await editor.getByRole('button',{name:'Try full editor',exact:true}).click();
 await expect(editor.locator('html')).toHaveAttribute('data-liberty-state','error',{timeout:60000});
 await expect(editor.locator('canvas')).toHaveCount(1);
 await expect(editor.locator('.editor-compatibility')).toHaveCount(0);
 await expect(page.locator('#demo-status')).toContainText('WebGL');
 expect(native.length).toBeGreaterThan(0);
});
