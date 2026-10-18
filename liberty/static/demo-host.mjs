import {msg,text,installLanguage,setLanguage} from './i18n.mjs';
import {watchEditorRuntime,deferNativePreloads} from './editor-runtime.mjs';
import {disableDemoImports,installDemoImports} from './demo-guard.mjs';
import {createDemoBudget,demoPolicy} from './demo-policy.mjs';
import {graphicsAvailable,mountLightEditor} from './light-editor.mjs';
import {installCanvasDensity} from './canvas-density.mjs';
import {installDemoExports} from './demo-download.mjs';
import {acquireDemoEngine} from './demo-session.mjs';
const config=JSON.parse(document.getElementById('__liberty-config').textContent);
const nonce=location.hash.slice(1),restoreNativePreloads=deferNativePreloads(document);
let phase='waiting',downloads=null,unloaded=false,stopRuntime=()=>{};
let stopImports=disableDemoImports(window,value=>state(value));
const seen=new Set();
installLanguage(window);installCanvasDensity(window);
document.documentElement.dataset.libertyState='waiting';
function state(value){
 if(phase==='starting'||phase==='active')window.parent.postMessage({type:'liberty.demo.state',nonce,text:value},config.portalOrigin);
}
function dispose(){
 if(phase==='stopped')return;
 phase='stopped';stopRuntime();downloads?.dispose();stopImports();stopImports=disableDemoImports(window,()=>{});
}
async function start(){
 await acquireDemoEngine(window,{portalOrigin:config.portalOrigin,nonce});
 if(unloaded)return;
 // Only the portal may initiate local downloads. No account or Drive API exists here.
 downloads=installDemoExports(window,{portalOrigin:config.portalOrigin,onState:state});
 const useLight=config.appId==='wordcraft'&&(new URLSearchParams(location.search).has('light')||!await graphicsAvailable(window));
 if(phase==='stopped'||unloaded)return;
 const budget=createDemoBudget(),policy=demoPolicy(config.appId,{light:useLight});let lightEditor=null;
 stopImports();stopImports=installDemoImports(window,{budget,policy,notify:state,onFiles:useLight?files=>lightEditor.openFile(files[0]):null});
 if(useLight){
  lightEditor=mountLightEditor(window,{demo:true,onState:state,onSave:downloads.exportBlob,
   admit:async options=>Promise.all((await window.showOpenFilePicker(options)).map(handle=>handle.getFile()))});return;
 }
 stopRuntime=watchEditorRuntime(window,(value,message)=>{document.documentElement.dataset.libertyState=value;state(message)});
 restoreNativePreloads();
 for(const inert of document.querySelectorAll('script[type="application/x-liberty-module"]')){
  const script=document.createElement('script');for(const attr of inert.attributes)if(attr.name!=='type')script.setAttribute(attr.name,attr.value);
  script.type='module';script.textContent=inert.textContent;inert.replaceWith(script);
 }
}
async function receive(event){
 if(event.source!==window.parent||event.origin!==config.portalOrigin)return;
 const data=event.data;
 if(data?.type==='liberty.language'&&['en','pt-BR'].includes(data.language)){setLanguage(data.language);return}
 if(!/^[A-Za-z0-9_-]{24,80}$/.test(nonce)||!data||data.type!=='liberty.demo.engine'||data.nonce!==nonce||
  typeof data.requestId!=='string'||!/^[A-Za-z0-9_-]{8,80}$/.test(data.requestId)||
  !['start','stop'].includes(data.action)||Object.keys(data).length!==4||
  !Object.keys(data).every(key=>['type','nonce','requestId','action'].includes(key))||seen.has(data.requestId))return;
 seen.add(data.requestId);if(seen.size>32)seen.delete(seen.values().next().value);
 const reply=status=>window.parent.postMessage({type:'liberty.demo.engine',nonce,requestId:data.requestId,status},config.portalOrigin);
 if(data.action==='stop'){dispose();reply('stopped');return}
 if(phase!=='waiting'){reply('failed');return}
 phase='starting';
 try{await start();if(phase==='stopped')return;phase='active';reply('started')}
 catch{
  document.documentElement.dataset.libertyState='error';
  const message=text(msg('Não foi possível iniciar a demonstração com armazenamento isolado neste navegador. Tente outro perfil ou navegador.'));
  document.body.textContent=message;state(message);dispose();reply('failed');
 }
}
window.addEventListener('message',receive);
// Keep the lease until the browser destroys the document. pagehide can freeze
// it for history navigation; neither pagehide nor a stop ACK proves destruction.
window.addEventListener('pagehide',()=>{unloaded=true;dispose();window.removeEventListener('message',receive)},{once:true});
