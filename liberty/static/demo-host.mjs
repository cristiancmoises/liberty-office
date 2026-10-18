import {msg,text,installLanguage,setLanguage} from './i18n.mjs';;
import {clearEditorIdentity} from './editor-storage.mjs';
import {watchEditorRuntime,deferNativePreloads} from './editor-runtime.mjs';
import {disableDemoImports} from './demo-guard.mjs';
import {graphicsAvailable,mountLightEditor} from './light-editor.mjs';
import {installCanvasDensity} from './canvas-density.mjs';
import {installDemoExports} from './demo-download.mjs';
const config=JSON.parse(document.getElementById('__liberty-config').textContent);
const restoreNativePreloads=deferNativePreloads(document);
installLanguage(window);
installCanvasDensity(window);
window.addEventListener('message',event=>{if(event.source===window.parent&&event.origin===config.portalOrigin&&event.data?.type==='liberty.language'&&['en','pt-BR'].includes(event.data.language))setLanguage(event.data.language)});
function state(text){window.parent.postMessage({type:'liberty.demo.state',text},config.portalOrigin)}
async function start(){
 disableDemoImports(window,state);
 // The portal starts local downloads; isolated iframe Blob downloads fail in
 // some browsers. This adapter has no connection to the authenticated Drive.
 const downloads=installDemoExports(window,{portalOrigin:config.portalOrigin,onState:state});
 // This origin is exclusively for public demonstrations. Never clear private
 // editor storage: deployments must give demo its own origin.
 await clearEditorIdentity('demo-'+crypto.randomUUID(),{local:localStorage,session:sessionStorage,indexed:indexedDB,filesystem:navigator.storage,caches:window.caches,locks:navigator.locks});
 if(config.appId==='wordcraft'&&(new URLSearchParams(location.search).has('light')||!await graphicsAvailable(window))){
  mountLightEditor(window,{demo:true,onState:state,onSave:downloads.exportBlob});return;
 }
 watchEditorRuntime(window,(phase,text)=>{document.documentElement.dataset.libertyState=phase;state(text)});
 restoreNativePreloads();
 for(const inert of document.querySelectorAll('script[type="application/x-liberty-module"]')){
  const script=document.createElement('script');for(const attr of inert.attributes)if(attr.name!=='type')script.setAttribute(attr.name,attr.value);
  script.type='module';script.textContent=inert.textContent;inert.replaceWith(script);
 }
}
start().catch(()=>{document.documentElement.dataset.libertyState='error';document.body.textContent=text(msg('Não foi possível iniciar a demonstração com armazenamento isolado neste navegador. Tente outro perfil ou navegador.'));state(document.body.textContent)});
