import {clearEditorIdentity} from './editor-storage.mjs';
import {watchEditorRuntime} from './editor-runtime.mjs';
import {disableDemoImports} from './demo-guard.mjs';
import {graphicsAvailable,mountLightEditor} from './light-editor.mjs';
import {createWritable} from './bridge.mjs';
const config=JSON.parse(document.getElementById('__liberty-config').textContent);
function state(text){window.parent.postMessage({type:'liberty.demo.state',text},config.portalOrigin)}
async function download(blob,name){const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000)}
async function start(){
 disableDemoImports(window,state);
 // Native save pickers reject cross-origin frames. Demonstrations export only
 // a browser download; there is no connection to the authenticated Drive.
 window.showSaveFilePicker=async(options={})=>({kind:'file',name:options.suggestedName||'exemplo.bin',createWritable:async()=>createWritable(blob=>download(blob,options.suggestedName||'exemplo.bin'))});
 // This origin is exclusively for public demonstrations. Never clear private
 // editor storage: deployments must give demo its own origin.
 await clearEditorIdentity('demo-'+crypto.randomUUID(),{local:localStorage,session:sessionStorage,indexed:indexedDB,filesystem:navigator.storage,caches:window.caches,locks:navigator.locks});
 if(config.appId==='wordcraft'&&(new URLSearchParams(location.search).has('light')||!await graphicsAvailable(window))){
  mountLightEditor(window,{demo:true,onState:state,onSave:download});return;
 }
 watchEditorRuntime(window,(phase,text)=>{document.documentElement.dataset.libertyState=phase;state(text)});
 for(const inert of document.querySelectorAll('script[type="application/x-liberty-module"]')){
  const script=document.createElement('script');for(const attr of inert.attributes)if(attr.name!=='type')script.setAttribute(attr.name,attr.value);
  script.type='module';script.textContent=inert.textContent;inert.replaceWith(script);
 }
}
start().catch(()=>{document.documentElement.dataset.libertyState='error';document.body.textContent='Não foi possível iniciar a demonstração com armazenamento isolado neste navegador. Tente outro perfil ou navegador.';state(document.body.textContent)});
