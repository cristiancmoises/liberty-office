import {test,expect} from '@playwright/test';
import {createHmac,randomBytes} from 'node:crypto';
import {readFile} from 'node:fs/promises';

const origin=process.env.LIBERTY_SIGNUP_ORIGIN;
const seedPath=process.env.LIBERTY_SIGNUP_SEED;
test.skip(!origin||!seedPath,'Requires an explicitly seeded, disposable signup runtime.');
if(origin){const url=new URL(origin);if(url.hostname!=='localhost'||url.protocol!=='http:'||url.port!=='18597')throw Error('Signup mutations require the isolated localhost:18597 preview.');}
const password='Browser-signup-test-only-2026!';
const name=prefix=>prefix+randomBytes(6).toString('hex');
function totp(secret){
 let accumulator=0,bits=0;const bytes=[],alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
 for(const letter of secret){const value=alphabet.indexOf(letter);if(value<0)throw Error('Unexpected TOTP alphabet');accumulator=(accumulator<<5)|value;bits+=5;if(bits>=8){bits-=8;bytes.push((accumulator>>>bits)&255);accumulator&=(1<<bits)-1}}
 const counter=Buffer.alloc(8);counter.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));
 const digest=createHmac('sha1',Buffer.from(bytes)).update(counter).digest();
 return String((digest.readUInt32BE(digest[19]&15)&0x7fffffff)%1e6).padStart(6,'0');
}
async function operator(playwright){
 const seed=JSON.parse(await readFile(seedPath,'utf8'));
 expect(seed.origin).toBe(origin);
 return playwright.request.newContext({baseURL:origin,extraHTTPHeaders:{Cookie:seed.operator_cookie,'X-CSRF-Token':seed.operator_csrf,Origin:origin}});
}
async function openSignup(page,username){
 await page.goto(origin);
 await page.getByRole('button',{name:'Create a free account',exact:true}).click();
 await page.locator('input[name=name]').fill('Synthetic visitor');
 await page.locator('input[name=username]').fill(username);
 await page.locator('input[name=password]').fill(password);
}

for(const width of [320,390,768,780,1024,1280,1440])for(const language of ['en','pt-BR']){
 test(`free account form is accessible and fits ${language} at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:900});
  const posts=[],errors=[];page.on('request',request=>{if(request.method()==='POST')posts.push(request.url())});
  page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(['error','warning'].includes(message.type()))errors.push(message.text())});
  await openSignup(page,'typed-visitor');
  await expect(page.locator('.auth-card')).toContainText('100 MB = 100,000,000 bytes');
  if(language==='pt-BR')await page.getByLabel('Language / Idioma').selectOption('pt-BR');
  await expect(page.locator('html')).toHaveAttribute('lang',language);
  await expect(page.locator('input[name=username]')).toHaveValue('typed-visitor');
  await expect(page.locator('input[name=password]')).toHaveValue(password);
  await expect(page.locator('.auth-card')).toContainText(language==='en'?'100 MB = 100,000,000 bytes':'100 MB = 100.000.000 bytes');
  await expect(page.locator('input[name=role],input[name=quota],select[name=role]')).toHaveCount(0);
  await page.locator('input[name=name]').focus();await page.keyboard.press('Tab');
  await expect(page.locator('input[name=username]')).toBeFocused();
  await page.keyboard.press('Tab');await expect(page.locator('input[name=password]')).toBeFocused();
  const username=page.locator('input[name=username]');
  for(const value of ['a-b.c_d','abc123']){await username.fill(value);expect(await username.evaluate(node=>node.checkValidity())).toBe(true)}
  for(const value of ['-abc','ab!c','a b','ABC']){await username.fill(value);expect(await username.evaluate(node=>node.checkValidity())).toBe(false)}
  await username.fill('typed-visitor');
  const bounds=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,controls:[...document.querySelectorAll('.auth-card input,.auth-card button')].map(n=>{const r=n.getBoundingClientRect();return {left:r.left,right:r.right}})}));
  expect(bounds.scroll).toBeLessThanOrEqual(bounds.width);
  for(const control of bounds.controls){expect(control.left).toBeGreaterThanOrEqual(0);expect(control.right).toBeLessThanOrEqual(bounds.width)}
  expect(posts).toEqual([]);
  expect(errors).toEqual([]);
  await expect(page.locator('main.auth-content h1')).toHaveCount(1);
 });
}

test('a free account enrolls MFA, saves to Drive and downloads even at its quota',async({page,playwright})=>{
 const username=name('visitor');
 await openSignup(page,username);
 await page.locator('form button[type=submit]').click();
 await expect(page.locator('#mfa-qr .secret')).toBeVisible();
 await expect(page.locator('#workspace')).toHaveCount(0);
 const secret=(await page.locator('#mfa-qr .secret').textContent()).trim();
 await page.locator('input[name=code]').fill(totp(secret));
 await page.locator('form button[type=submit]').click();
 await expect(page.locator('.recovery-codes code')).toHaveCount(10);
 await expect(page.locator('#workspace')).toHaveCount(0);
 await page.locator('.auth-card button.primary').click();
 await expect(page.locator('#workspace')).toBeVisible();
 const status=await (await page.request.get(origin+'/api/auth/status')).json();
 expect(status.user.role).toBe('user');expect(status.user.quota).toBe(100_000_000);
 await page.getByRole('button',{name:'My Drive',exact:true}).click();
 const chooser=page.waitForEvent('filechooser');
 await page.getByRole('button',{name:'Upload file',exact:true}).click();
 await (await chooser).setFiles({name:'personal.txt',mimeType:'text/plain',buffer:Buffer.from('hello\n')});
 await expect(page.getByRole('button',{name:'personal.txt',exact:true})).toBeVisible();
 const admin=await operator(playwright);
 try{const changed=await admin.patch('/api/admin/users/'+status.user.id,{data:{quota:6}});expect(changed.ok()).toBe(true)}finally{await admin.dispose()}
 await page.reload();
 await page.getByRole('button',{name:'My Drive',exact:true}).click();
 await expect(page.getByRole('button',{name:'Upload file',exact:true})).toBeDisabled();
 await expect(page.getByRole('button',{name:'Download',exact:true})).toBeEnabled();
 const downloaded=page.waitForEvent('download');
 await page.getByRole('button',{name:'Download',exact:true}).click();
 const file=await downloaded;expect(await file.failure()).toBeNull();
 expect((await readFile(await file.path())).toString()).toBe('hello\n');
});

test('a committed signup with a lost reply never silently creates a second account',async({page,playwright})=>{
 const username=name('uncertain');let posts=0;
 await page.route('**/api/auth/signup',async route=>{
  posts++;
  if(posts===1){const result=await route.fetch();expect(result.status()).toBe(201);await page.context().clearCookies();await route.abort('failed')}
  else await route.continue();
 });
 await openSignup(page,username);
 await page.locator('form button[type=submit]').click();
 await expect(page.locator('.auth-card .warning')).toBeVisible();
 await expect(page.locator('form button[type=submit]')).toBeEnabled();
 expect(posts).toBe(1);
 await expect(page.locator('input[name=username]')).toHaveValue(username);
 await page.locator('form button[type=submit]').click();
 await expect(page.locator('#notifications')).toContainText('That username is already registered.');
 expect(posts).toBe(2);
 const admin=await operator(playwright);
 try{const users=await (await admin.get('/api/admin/users')).json();expect(users.users.filter(user=>user.username===username)).toHaveLength(1)}finally{await admin.dispose()}
 await page.getByRole('button',{name:'Back to sign in',exact:true}).click();
 await page.locator('input[name=username]').fill(username);
 await page.locator('input[name=password]').fill(password);
 await page.locator('form button[type=submit]').click();
 await expect(page.locator('#mfa-qr img')).toBeVisible();
});
