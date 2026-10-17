import test from 'node:test';import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';
import {parseHTML} from 'linkedom';
const tick=()=>new Promise(resolve=>setTimeout(resolve,5));
async function waitFor(fn){for(let i=0;i<100;i++){if(fn())return;await tick()}throw Error('DOM condition timeout')}

test('portal renders admin account controls without injecting filenames',async()=>{
 const html=await readFile(new URL('../liberty/static/index.html',import.meta.url),'utf8');const {window}=parseHTML(html);
 const location={href:'http://localhost/',origin:'http://localhost',hash:'',search:'',pathname:'/',reload(){}},history={replaceState(){}};
 Object.assign(globalThis,{window,document:window.document,Node:window.Node,location,history});
 window.location=location;window.history=history;
 Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return this.querySelector('option[selected]')?.value||this.querySelector('option')?.value},set(value){for(const o of this.querySelectorAll('option'))o.selected=o.value===value}});
 window.HTMLElement.prototype.showModal=function(){this.setAttribute('open','')};window.HTMLElement.prototype.close=function(){this.dispatchEvent(new window.Event('close'))};
 const me={id:'me',username:'admin',name:'Admin',role:'admin',enabled:true,totp_confirmed:1,quota:1e9};
 globalThis.fetch=async(url,options={})=>{
  let body;
  if(url==='/api/auth/status')body={state:'full',setup_required:false,csrf:'test',user:me};
  else if(url==='/api/apps')body={apps:[{id:'wordcraft',name:'WordCraft',description:'Documentos',monogram:'W',category:'Documentos',extensions:['txt'],installed:true,launch_url:'/api/editors/wordcraft'}]};
  else if(url==='/api/storage')body={used:3,quota:1e9,max_upload:1e6,global_used:3,global_quota:1e10};
  else if(String(url).startsWith('/api/files?'))body={files:[{id:'f',owner:'me',name:'<img src=x onerror=alert(1)>.txt',kind:'file',updated:1,size:3,etag:'"v"',version:'v'}],breadcrumbs:[]};
  else if(url==='/api/admin/users')body={users:[{...me,activated:true,used:3},{id:'alice',username:'alice',name:'Alice',role:'user',enabled:true,activated:false,totp_confirmed:0,used:0,quota:1e9}]};
  else if(url==='/api/auth/sessions')body={sessions:[{id:'session',current:true,auth_at:1,expires:9999999999}]};
  else throw Error('Unexpected route '+url);
  return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
 };
 await import('../liberty/static/app.js?dom-test');await waitFor(()=>document.querySelector('#workspace table'));
 assert.equal(document.querySelector('#workspace table img'),null);
 assert.match(document.querySelector('#workspace').textContent,/<img src=x onerror=alert\(1\)>/);
 const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent===text);
 button('Administration').click();await waitFor(()=>document.querySelector('.user-controls'));
 assert.ok(document.querySelector('button[aria-label="Recovery for alice"]'));
 button('My account').click();await waitFor(()=>button('Manage sessions'));
 button('Manage sessions').click();await waitFor(()=>document.querySelector('dialog'));
 assert.match(document.querySelector('dialog').textContent,/Current session/);
 const select=document.querySelector('.language-selector select');select.value='pt-BR';select.dispatchEvent(new window.Event('change'));
 assert.match(document.querySelector('dialog').textContent,/Sessão atual/);
 assert.equal(document.documentElement.lang,'pt-BR');
 document.querySelector('dialog button[aria-label="Fechar"]').click();
});
