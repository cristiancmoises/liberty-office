import {msg,text,bindText,bindAttribute,getLanguage,installLanguage,languageSelector,languageURL,onLanguageChange,ownedMessage} from './i18n.mjs';
import {viewControls} from './view-controls.mjs';
import {connectDemoDownloads} from './demo-download.mjs';
import {connectDemoSession,connectDemoEngine} from './demo-session.mjs';
installLanguage(window);
document.querySelector('.demo-banner').append(languageSelector(document));
const launcher=document.querySelector('#demo-launcher'),editor=document.querySelector('#demo-editor'),holder=document.querySelector('#demo-frame'),status=document.querySelector('#demo-status');
const closeButton=document.querySelector('#demo-close'),message=document.querySelector('#demo-message');
document.querySelector('.demo-toolbar').append(viewControls(editor));
bindAttribute(document.querySelector('#demo-apps'),'aria-label',msg('Aplicativos de demonstração'));
bindAttribute(editor,'aria-label',msg('Editor de demonstração'));
let current=null;
const show=value=>bindText(status,ownedMessage(value));
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
 const session={origin,nonce,controller,frame:null,phase:'acquiring'};current=session;
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
  show(error.message+' Finish and clear to retry. Cleanup has not been confirmed.');
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
 }catch(error){session.phase='blocked';show(error.message+' Do not start another demo until cleanup is confirmed.')}
 finally{closeButton.disabled=false}
}
closeButton.addEventListener('click',()=>{
 if(confirm(text(msg('Sair da demonstração? As alterações não são salvas no servidor.'))))finishDemoSession();
});
window.addEventListener('pagehide',()=>{current?.downloads?.dispose();current?.channel?.dispose();current?.engine?.dispose()});
window.addEventListener('message',event=>{
 const session=current,data=event.data;
 if(session?.phase==='active'&&event.source===session.frame?.contentWindow&&event.origin===session.origin&&
  data?.type==='liberty.demo.state'&&data.nonce===session.nonce&&typeof data.text==='string'&&Object.keys(data).length===3)show(data.text.slice(0,500));
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
