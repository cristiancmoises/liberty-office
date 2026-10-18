import {msg,text,bindText,bindAttribute,getLanguage,installLanguage,languageSelector,languageURL,onLanguageChange,ownedMessage} from './i18n.mjs';
import {viewControls} from './view-controls.mjs';
import {connectDemoDownloads} from './demo-download.mjs';
import {connectDemoSession,connectDemoEngine} from './demo-session.mjs';
import {DEMO_LIMITS,demoPolicy} from './demo-policy.mjs';
installLanguage(window);
const language=languageSelector(document),privacy=document.querySelector('#demo-privacy');
document.querySelector('.demo-banner').append(language);
const launcher=document.querySelector('#demo-launcher'),editor=document.querySelector('#demo-editor'),holder=document.querySelector('#demo-frame'),status=document.querySelector('#demo-status');
const closeButton=document.querySelector('#demo-close'),message=document.querySelector('#demo-message');
document.querySelector('.demo-toolbar').append(viewControls(editor));
bindAttribute(document.querySelector('#demo-apps'),'aria-label',msg('Aplicativos de demonstração'));
bindAttribute(editor,'aria-label',msg('Editor de demonstração'));
let current=null;
const show=value=>bindText(status,ownedMessage(value));
function workflow(session){
 const policy=demoPolicy(session.app.id,{light:session.light});
 const open=session.light?msg('Abrir TXT/HTML'):session.app.id==='wordcraft'?msg('Arquivo → Abrir → Procurar'):msg('Arquivo → Abrir');
 const save=session.light?msg('Baixar cópia'):session.app.id==='lightcraft'?msg('Arquivo → Exportar'):msg('Arquivo → Salvar/Exportar (Ctrl+S)');
 bindText(document.querySelector('#demo-guide'),session.app.id==='deckcraft'?
  msg('Arquivo → Abrir insere slides do roteiro. Selecione o novo slide e clique duas vezes no texto para editar. Baixe com Ctrl+S; depois conclua e limpe.'):
  policy.qualified?
  msg('1. Abra: {0}. 2. Edite. 3. Baixe: {1}. 4. Conclua e limpe.',open,save):
  msg('Crie ou edite o exemplo. Baixe: {0}. Depois conclua e limpe.',save));
 bindText(document.querySelector('#demo-format'),policy.qualified?
  msg('Formatos locais: {0} · até {1} MiB por arquivo. Outros formatos não estão habilitados nesta demo.',policy.extensions.join(', '),policy.maxFileBytes/(1024*1024)):
  msg('Importação local bloqueada: {0}',ownedMessage(policy.reason)));
 const budget=document.querySelector('#demo-budget');budget.dataset.files=String(session.files);budget.dataset.bytes=String(session.bytes);
 bindText(budget,msg('Projeto: {0}/{1} arquivos · {2}/{3} MB lidos. Teto geral: {4} MB/arquivo; limites do formato prevalecem.',
  session.files,DEMO_LIMITS.maxProjectFiles,(session.bytes/1_000_000).toFixed(2),DEMO_LIMITS.maxProjectBytes/1_000_000,DEMO_LIMITS.maxFileBytes/1_000_000));
}
function frameElement(name){
 const frame=document.createElement('iframe');frame.name=name;
 frame.sandbox='allow-scripts allow-same-origin allow-downloads';frame.referrerPolicy='no-referrer';return frame;
}
function loaded(frame,attach){
 return new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>{done();reject(Error('Demo frame did not load.'))},15000);
  const done=()=>{clearTimeout(timer);frame.removeEventListener('load',ready);frame.removeEventListener('error',failed)};
  const ready=()=>{done();resolve()};const failed=()=>{done();reject(Error('Demo frame failed to load.'))};
  frame.addEventListener('load',ready);frame.addEventListener('error',failed);attach();
 });
}
async function unloadEngine(session){
 if(session.unload)return session.unload;
 if(!session.frame)return;
 const frame=session.frame;session.engine?.dispose();
 // Navigation completion is the barrier: a stop ACK alone cannot terminate
 // native WASM/workers or an outstanding file operation.
 session.unload=loaded(frame,()=>{frame.src='about:blank'}).then(()=>{
  frame.remove();session.frame=null;
 });
 try{await session.unload}finally{session.unload=null}
}
function reset(session){
 session.channel?.dispose();session.engine?.dispose();session.controller.remove();session.downloads?.dispose();
 if(current!==session)return;
 current=null;holder.replaceChildren();editor.hidden=true;launcher.hidden=false;closeButton.disabled=false;
 document.querySelector('#demo-launcher-notice').append(privacy);document.querySelector('.demo-banner').append(language);
 editor.classList.remove('is-focused');
 const focus=editor.querySelector('[aria-pressed]');focus.setAttribute('aria-pressed','false');bindText(focus,msg('Modo foco'));
 if(document.fullscreenElement===editor)document.exitFullscreen().catch(()=>{});
 document.querySelector('#demo-apps button')?.focus();
}
function interrupted(session,controller){
 if(controller)session.invalidController=true;
 if(session.unload)return;
 if(current!==session||session.phase==='finishing'||session.phase==='closed')return;
 session.phase='blocked';session.downloads?.suspend();
 unloadEngine(session).catch(()=>{});
 show('Demo interrupted. Finish and clear before starting again. If the session controller reloaded, reload this page to recover.');
}
export async function openDemoSession(app){
 if(current)return;
 const origin=new URL(app.url).origin,nonce=crypto.randomUUID(),controller=frameElement('liberty-demo-controller');
 controller.hidden=true;controller.src=origin+'/demo/controller#'+nonce;
 const session={app,origin,nonce,controller,frame:null,phase:'acquiring',light:false,files:0,bytes:0};current=session;
 workflow(session);document.querySelector('#demo-editor-notice').append(privacy);document.querySelector('.demo-toolbar').append(language);
 document.querySelector('#demo-name').textContent=app.name;bindText(status,msg('Carregando {0}…',app.name));
 launcher.hidden=true;editor.hidden=false;closeButton.disabled=true;
 try{
  await loaded(controller,()=>document.body.append(controller));
  session.channel=connectDemoSession(window,{frame:controller,origin,nonce});
  controller.addEventListener('load',()=>interrupted(session,true));
  const result=await session.channel.request('acquire');
  if(result!=='ready'){
   if(result==='busy'||result==='failed'){
    const value=result==='busy'?'Another demo is already open in this browser. Finish it before opening another.':
     'Cannot safely prepare temporary demo storage in this browser. Close other demo tabs or try another browser.';
    reset(session);bindText(message,ownedMessage(value));return;
   }
   throw Error('Demo session was not admitted.');
  }
  if(session.invalidController)throw Error('Demo session controller reloaded.');
  const frame=frameElement('liberty-demo-engine');session.frame=frame;
  bindAttribute(frame,'title',msg('{0} — demonstração',app.name));
  const url=new URL(languageURL(app.url,getLanguage()));url.hash=nonce;frame.src=url.href;
  session.downloads=connectDemoDownloads(window,{frame,origin,onState:value=>{if(current===session&&session.phase==='active')show(value)}});
  session.engine=connectDemoEngine(window,{frame,origin,nonce,timeoutMs:15000});
  await loaded(frame,()=>holder.replaceChildren(frame));
  frame.addEventListener('load',()=>interrupted(session,false));
  if(session.invalidController)throw Error('Demo session controller reloaded.');
  session.phase='active';
  if(await session.engine.request('start')!=='started')throw Error('Demo editor did not start. Finish and clear to retry.');
 }catch(error){
  session.phase='blocked';session.downloads?.suspend();
  try{await unloadEngine(session)}catch{}
  show(msg('{0} Use Concluir e limpar para tentar novamente. A limpeza não foi confirmada.',ownedMessage(error.message)));
 }finally{if(current===session){closeButton.disabled=false;closeButton.focus()}}
}
export async function finishDemoSession(){
 const session=current;if(!session||session.phase==='finishing')return;
 session.phase='finishing';closeButton.disabled=true;session.downloads?.suspend();
 show('Finishing demo and clearing temporary browser data…');
 try{
  if(session.frame){try{await session.engine.request('stop')}catch{}await unloadEngine(session)}
  if(session.invalidController)throw Error('The session controller reloaded. Reload this page to recover; cleanup is not confirmed.');
  if(!session.channel||await session.channel.request('clear')!=='cleared')throw Error('Temporary data cleanup is not complete. Close other demo tabs and retry Finish.');
  if(session.invalidController)throw Error('The session controller reloaded. Cleanup is not confirmed. Reload this page to recover.');
  session.downloads?.dispose();
  if(await session.channel.request('release')!=='cleared')throw Error('Temporary session release was not confirmed.');
  session.phase='closed';reset(session);bindText(message,ownedMessage('Demo finished. Temporary browser data was cleared. Your original files were not changed.'));
 }catch(error){session.phase='blocked';show(msg('{0} Não inicie outra demo até confirmar a limpeza.',ownedMessage(error.message)))}
 finally{closeButton.disabled=false}
}
closeButton.addEventListener('click',()=>{
 if(confirm(text(msg('Concluir e limpar? Baixe uma cópia primeiro. Os dados locais da demo serão apagados.'))))finishDemoSession();
});
window.addEventListener('pagehide',()=>{current?.downloads?.dispose();current?.channel?.dispose();current?.engine?.dispose()});
window.addEventListener('message',event=>{
 const session=current,data=event.data;
 if(session?.phase==='active'&&event.source===session.frame?.contentWindow&&event.origin===session.origin&&
  data?.nonce===session.nonce&&!Array.isArray(data)){
  if(data.type==='liberty.demo.state'&&typeof data.text==='string'&&Object.keys(data).length===3)show(data.text.slice(0,500));
  if(data.type==='liberty.demo.policy'&&typeof data.light==='boolean'&&Object.keys(data).length===3){session.light=session.app.id==='wordcraft'&&data.light;workflow(session)}
  if(data.type==='liberty.demo.budget'&&Object.keys(data).length===4&&Number.isSafeInteger(data.files)&&data.files>=session.files&&data.files<=DEMO_LIMITS.maxProjectFiles&&
   Number.isSafeInteger(data.bytes)&&data.bytes>=session.bytes&&data.bytes<=DEMO_LIMITS.maxProjectBytes){session.files=data.files;session.bytes=data.bytes;workflow(session)}
 }
});
onLanguageChange(language=>{if(current?.frame)current.frame.contentWindow.postMessage({type:'liberty.language',language},current.origin)});
try{
 const response=await fetch('/demo/apps',{headers:{'Accept-Language':getLanguage()},credentials:'omit'});if(!response.ok)throw Error(text(msg('Não foi possível carregar a demonstração.')));
 const {apps}=await response.json();
 for(const app of apps){
  const button=document.createElement('button');button.className='app-card';button.title=app.name;button.disabled=!app.installed;
  const icon=document.createElement('span');icon.className='app-icon '+app.id;icon.textContent=app.monogram;
  const name=document.createElement('h2');name.textContent=app.name;
  const description=document.createElement('p');bindText(description,app.installed?ownedMessage(app.description):msg('Indisponível neste servidor'));
  button.append(icon,name,description);button.addEventListener('click',()=>openDemoSession(app));document.querySelector('#demo-apps').append(button);
 }
 bindText(document.querySelector('#demo-message'),msg('Selecione um aplicativo para começar. Nenhum login é necessário.'));
}catch(error){document.querySelector('#demo-message').textContent=error.message}
