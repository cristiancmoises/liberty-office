import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {setTimeout as sleep} from 'node:timers/promises';
import {parseHTML} from 'linkedom';

async function until(check){for(let i=0;i<100;i++){if(check())return;await sleep(5)}throw Error('Signup DOM condition timeout')}

test('free signup retains locale/input, handles uncertain submission once and preserves full-quota downloads',async()=>{
 const {window}=parseHTML(await readFile(new URL('../liberty/static/index.html',import.meta.url),'utf8'));
 const location={href:'http://localhost/',origin:'http://localhost',hash:'',search:'',pathname:'/',reload(){}},history={replaceState(){}};
 Object.assign(globalThis,{window,document:window.document,Node:window.Node,location,history});window.location=location;window.history=history;
 Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value},set(value){for(const o of this.querySelectorAll('option'))o.selected=o.value===value}});
 globalThis.FormData=class{constructor(form){this.pairs=[...form.querySelectorAll('[name]')].filter(n=>!n.disabled).map(n=>[n.name,n.value])}[Symbol.iterator](){return this.pairs[Symbol.iterator]()}};
 let phase='anonymous',enabled=true,posts=0,checks=0;const payloads=[],opened=[];
 window.open=url=>opened.push(url);
 globalThis.fetch=async(url,options={})=>{
  let result;
  if(url==='/api/auth/status'){checks++;result={state:phase,setup_required:false,public_signup:enabled,signup_quota_bytes:100_000_000,...(phase!=='anonymous'?{csrf:'synthetic-csrf'}:{}),...(phase==='full'?{user:{id:'visitor',username:'visitor',name:'Visitor',role:'user',quota:100_000_000,enabled:true,totp_confirmed:1}}:{})}}
  else if(url==='/api/auth/signup'){posts++;payloads.push(JSON.parse(options.body));if(posts===1)throw TypeError('Synthetic lost response');phase='enroll';result={state:phase,csrf:'synthetic-csrf'}}
  else if(url==='/api/auth/mfa/setup')result={secret:'SYNTHETIC',qr_svg:'<svg xmlns="http://www.w3.org/2000/svg"/>'};
  else if(url==='/api/auth/mfa/verify'){phase='full';result={state:phase,recovery_codes:['synthetic-recovery-code']}}
  else if(url==='/api/auth/logout'){phase='anonymous';enabled=false;result={ok:true}}
  else if(url==='/api/apps')result={apps:[]};
  else if(url==='/api/storage')result={used:50_000_000,reserved:50_000_000,quota:100_000_000,max_upload:100_000_000};
  else if(String(url).startsWith('/api/files?'))result={files:[{id:'saved',owner:'visitor',name:'saved.txt',kind:'file',size:50_000_000,updated:1}],breadcrumbs:[]};
  else throw Error('Unexpected signup UI route '+url);
  return new Response(JSON.stringify(result),{status:url==='/api/auth/signup'?201:200,headers:{'Content-Type':'application/json'}});
 };
 const button=label=>[...document.querySelectorAll('button')].find(node=>node.textContent===label);
 await import('../liberty/static/app.js?signup-dom');
 await until(()=>document.querySelector('form'));
 assert.ok(button('Create a free account'));
 assert.equal(document.documentElement.lang,'en');
 button('Create a free account').click();
 await until(()=>document.querySelector('input[name=name]'));
 assert.equal(document.querySelectorAll('h1').length,1);
 assert.equal(document.querySelector('main.auth-content h1')?.textContent,'Create your Liberty workspace');
 const form=document.querySelector('form');
 assert.match(form.parentElement.textContent,/100 MB = 100,000,000 bytes/);
 for(const [name,value]of Object.entries({name:'Visitor',username:'visitor',password:'Synthetic-password-for-this-test!'}))form.querySelector(`[name=${name}]`).value=value;
 const select=document.querySelector('.language-selector select');select.value='pt-BR';select.dispatchEvent(new window.Event('change'));
 assert.equal(form.querySelector('[name=username]').value,'visitor');
 assert.equal(form.querySelector('[name=password]').value,'Synthetic-password-for-this-test!');
 assert.match(form.parentElement.textContent,/100 MB = 100\.000\.000 bytes/);
 const submit=form.querySelector('[type=submit]');
 form.dispatchEvent(new window.Event('submit',{cancelable:true}));
 await until(()=>posts===1&&!submit.disabled);
 assert.equal(posts,1,'lost response must not trigger an automatic second POST');
 assert.ok(checks>=2,'check existing status after an uncertain registration');
 assert.equal(document.querySelector('form'),form,'uncertainty preserves typed fields');
 form.dispatchEvent(new window.Event('submit',{cancelable:true}));
 await until(()=>document.querySelector('#mfa-qr img'));
 assert.equal(posts,2);assert.deepEqual(Object.keys(payloads[1]).sort(),['name','password','username']);
 assert.equal(document.querySelector('#workspace'),null);
 const mfa=document.querySelector('form');mfa.querySelector('[name=code]').value='123456';mfa.dispatchEvent(new window.Event('submit',{cancelable:true}));
 await until(()=>document.querySelector('.recovery-codes'));
 assert.equal(document.querySelector('#workspace'),null,'recovery acknowledgement precedes workspace');
 button('Guardei os códigos. Abrir meu espaço').click();
 await until(()=>document.querySelector('#workspace'));
 button('Meu Drive').click();await until(()=>button('Enviar arquivo'));
 assert.equal(button('Enviar arquivo').disabled,true,'used plus reserved consumes the quota');
 const download=document.querySelector('button[aria-label=Baixar]');assert.ok(download&&!download.disabled);download.click();assert.deepEqual(opened,['/api/files/saved/content']);
 assert.match(document.querySelector('.sidebar-bottom').textContent,/100/);
 document.querySelector('button[aria-label=Sair]').click();
 await until(()=>document.querySelector('input[name=password]'));
 assert.equal(button('Criar conta gratuita'),undefined,'disabled signup has no create-account action');
 assert.ok([...document.querySelectorAll('a')].some(a=>new URL(a.href,'http://localhost').pathname==='/demo'));
});
