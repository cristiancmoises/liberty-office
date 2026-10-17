import {test,expect} from '@playwright/test';
const origin=process.env.LIBERTY_DEMO_ORIGIN||'http://localhost:8097';

test('English login defaults and live Portuguese switch preserve form values',async({page})=>{
 await page.route('**/api/auth/status',route=>route.fulfill({json:{state:'anonymous',setup_required:false}}));
 await page.goto(origin+'/');
 await expect(page.getByRole('heading',{name:'Welcome back.'})).toBeVisible();
 await page.getByLabel('Username',{exact:true}).fill('Nome');
 await page.getByLabel('Password',{exact:true}).fill('unsaved synthetic password');
 await page.getByRole('combobox',{name:'Language / Idioma'}).selectOption('pt-BR');
 await expect(page.getByRole('heading',{name:'Bom ter você de volta.'})).toBeVisible();
 await expect(page.getByLabel('Usuário',{exact:true})).toHaveValue('Nome');
 await expect(page.getByLabel('Senha',{exact:true})).toHaveValue('unsaved synthetic password');
 await expect(page).toHaveURL(/lang=pt-BR/);
 await page.getByRole('combobox',{name:'Language / Idioma'}).selectOption('en');
 await expect(page.locator('html')).toHaveAttribute('lang','en');
});

test('demo locale and focus changes retain an open light document and make no private requests',async({page})=>{
 const privateRequests=[],errors=[];
 page.on('request',request=>{if(new URL(request.url()).pathname.startsWith('/api/'))privateRequests.push(request.url())});
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/demo/apps',async route=>{
  const response=await route.fetch(),body=await response.json();
  for(const app of body.apps)if(app.id==='wordcraft'){const url=new URL(app.url);url.searchParams.set('light','1');app.url=url.href}
  await route.fulfill({json:body});
 });
 await page.goto(origin+'/demo');
 await expect(page.getByRole('heading',{name:'Try your next workspace.'})).toBeVisible();
 await expect(page.locator('.app-card[title="WordCraft"]')).toContainText('Writing, reviewing, and documents.');
 await page.getByRole('combobox',{name:'Language / Idioma'}).selectOption('pt-BR');
 await expect(page.locator('.app-card[title="WordCraft"]')).toContainText('Escrita, revisão e documentos.');
 await page.getByRole('combobox',{name:'Language / Idioma'}).selectOption('en');
 await page.locator('.app-card[title="WordCraft"]').click();
 const editor=page.frameLocator('#demo-frame iframe');
 await expect(editor.getByRole('heading',{name:'Documents · light mode'})).toBeVisible();
 await editor.getByRole('textbox',{name:'Document content'}).fill('Nome — unsaved document');
 const frameURL=await page.locator('#demo-frame iframe').getAttribute('src');
 await page.getByRole('combobox',{name:'Language / Idioma'}).selectOption('pt-BR');
 await expect(editor.getByRole('heading',{name:'Documentos · modo leve'})).toBeVisible();
 await expect(editor.getByRole('textbox',{name:'Conteúdo do documento'})).toHaveText('Nome — unsaved document');
 await expect(page.locator('#demo-frame iframe')).toHaveAttribute('src',frameURL);
 await page.getByRole('button',{name:'Modo foco',exact:true}).click();
 await expect(page.locator('#demo-editor')).toHaveClass(/is-focused/);
 await expect(editor.getByRole('textbox',{name:'Conteúdo do documento'})).toHaveText('Nome — unsaved document');
 await page.getByRole('button',{name:'Sair do foco',exact:true}).click();
 await page.getByRole('combobox',{name:'Language / Idioma'}).selectOption('en');
 await expect(editor.getByRole('button',{name:'Download copy'})).toBeVisible();
 await page.getByRole('button',{name:'Full screen',exact:true}).click();
 await expect.poll(()=>page.evaluate(()=>document.fullscreenElement?.id)).toBe('demo-editor');
 await expect(page.locator('.demo-badge')).toBeVisible();
 await page.getByRole('button',{name:'Exit full screen',exact:true}).click();
 await expect(editor.getByRole('textbox',{name:'Document content'})).toHaveText('Nome — unsaved document');
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await expect(page.locator('.demo-badge')).toHaveText('Public demo');
 expect(privateRequests).toEqual([]);expect(errors).toEqual([]);
});
