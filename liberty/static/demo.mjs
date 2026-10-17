import {msg,text,bindText,bindAttribute,getLanguage,installLanguage,languageSelector,languageURL,onLanguageChange} from './i18n.mjs';;
import {ownedMessage} from './i18n.mjs';
import {viewControls} from './view-controls.mjs';
import {connectDemoDownloads} from './demo-download.mjs';
installLanguage(window);
document.querySelector('.demo-banner').append(languageSelector(document));
const launcher=document.querySelector('#demo-launcher'),editor=document.querySelector('#demo-editor'),holder=document.querySelector('#demo-frame'),status=document.querySelector('#demo-status');
document.querySelector('.demo-toolbar').append(viewControls(editor));
bindAttribute(document.querySelector('#demo-apps'),'aria-label',msg('Aplicativos de demonstração'));
bindAttribute(editor,'aria-label',msg('Editor de demonstração'));
let current=null;
function open(app){
 const frame=document.createElement('iframe');bindAttribute(frame,'title',msg('{0} — demonstração',app.name));
 frame.sandbox='allow-scripts allow-same-origin allow-downloads';frame.referrerPolicy='no-referrer';
 current?.downloads.dispose();
 frame.src=languageURL(app.url,getLanguage());current={frame,origin:new URL(app.url).origin};
 current.downloads=connectDemoDownloads(window,{frame,origin:current.origin,onState:value=>bindText(status,ownedMessage(value))});
 document.querySelector('#demo-name').textContent=app.name;bindText(status,msg('Carregando {0}…',app.name));
 holder.replaceChildren(frame);launcher.hidden=true;editor.hidden=false;document.querySelector('#demo-close').focus();
}
document.querySelector('#demo-close').addEventListener('click',()=>{if(!confirm(text(msg('Sair da demonstração? As alterações não são salvas no servidor.'))))return;current?.downloads.dispose();holder.replaceChildren();current=null;editor.hidden=true;launcher.hidden=false;document.querySelector('#demo-apps button')?.focus()});
window.addEventListener('pagehide',()=>current?.downloads.dispose());
window.addEventListener('message',event=>{if(current&&event.source===current.frame.contentWindow&&event.origin===current.origin&&event.data?.type==='liberty.demo.state'&&typeof event.data.text==='string')bindText(status,ownedMessage(event.data.text.slice(0,500)))});
onLanguageChange(language=>{if(current)current.frame.contentWindow.postMessage({type:'liberty.language',language},current.origin)});
try{
 const response=await fetch('/demo/apps',{headers:{'Accept-Language':getLanguage()},credentials:'omit'});if(!response.ok)throw Error(text(msg('Não foi possível carregar a demonstração.')));
 const {apps}=await response.json();
 for(const app of apps){
  const button=document.createElement('button');button.className='app-card';button.title=app.name;button.disabled=!app.installed;
  const icon=document.createElement('span');icon.className='app-icon '+app.id;icon.textContent=app.monogram;
  const name=document.createElement('h2');name.textContent=app.name;
  const description=document.createElement('p');bindText(description,app.installed?ownedMessage(app.description):msg('Indisponível neste servidor'));
  button.append(icon,name,description);button.addEventListener('click',()=>open(app));document.querySelector('#demo-apps').append(button);
 }
 bindText(document.querySelector('#demo-message'),msg('Selecione um aplicativo para começar. Nenhum login é necessário.'));
}catch(error){document.querySelector('#demo-message').textContent=error.message}
