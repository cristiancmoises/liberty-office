import {attachBridge} from './bridge.mjs';
import {clearEditorIdentity} from './editor-storage.mjs';
const config=JSON.parse(document.getElementById('__liberty-config').textContent);
const documentId=crypto.randomUUID();
let port=null,sequence=0;const pending=new Map();
function state(text){if(port)port.postMessage({type:'state',text})}
const accountChannel=typeof BroadcastChannel==='function'?new BroadcastChannel('liberty.account'):null;
if(accountChannel)accountChannel.onmessage=event=>{if(event.data?.identity&&event.data.identity!==config.identity)window.location.replace('about:blank')};
async function exportBlob(blob,name){
 if(!port)throw Error('Conexão com o portal indisponível.');
 if(blob.size>config.maxBytes)throw Error('Exportação acima do limite de envio.');
 const buffer=await blob.arrayBuffer(),id='export-'+(++sequence);
 return new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>{pending.delete(id);reject(Error('O portal não confirmou o salvamento.'))},310000);
  pending.set(id,{resolve,reject,timer});port.postMessage({type:'export',id,name,buffer},[buffer]);
 });
}
async function start(){
 // Release old-account documents in other tabs before opening this account.
 accountChannel?.postMessage({identity:config.identity});
 await clearEditorIdentity(config.identity,{local:localStorage,session:sessionStorage,indexed:indexedDB,filesystem:navigator.storage,caches:window.caches,locks:navigator.locks});
 const bridge=attachBridge(window,{onExport:exportBlob,onState:state,maxBytes:config.maxBytes});
 await new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>{window.removeEventListener('message',connect);reject(Error('Abra este editor pelo portal Liberty Office.'))},45000);
  function connect(event){
   if(event.source!==window.parent||event.origin!==config.portalOrigin||event.data?.type!=='liberty.connect'||event.data.nonce!==config.nonce||event.data.documentId!==documentId||event.ports.length!==1)return;
   window.removeEventListener('message',connect);clearTimeout(timer);port=event.ports[0];
   port.onmessage=e=>{
    const data=e.data;
    if(data?.type==='offer'&&typeof data.name==='string'&&data.buffer instanceof ArrayBuffer&&data.buffer.byteLength<=config.maxBytes){
     bridge.offer(new Blob([data.buffer]),data.name);port.postMessage({type:'offer-ack'});
    }else if(data?.type==='result'&&pending.has(data.id)){
     const item=pending.get(data.id);pending.delete(data.id);clearTimeout(item.timer);
     if(data.ok)item.resolve();else{const error=Error(data.error||'Falha ao salvar.');error.recovered=!!data.recovered;item.reject(error)}
    }
   };port.start();resolve();
  }
  window.addEventListener('message',connect);window.parent.postMessage({type:'liberty.ready',nonce:config.nonce,documentId},config.portalOrigin);
 });
 document.documentElement.dataset.libertyState='ready';
 // Start the original modules only after identity cleanup and bridge initialization.
 for(const inert of document.querySelectorAll('script[type="application/x-liberty-module"]')){
  const script=document.createElement('script');for(const attr of inert.attributes)if(attr.name!=='type')script.setAttribute(attr.name,attr.value);
  script.type='module';script.textContent=inert.textContent;inert.replaceWith(script);
 }
}
start().catch(error=>{const node=document.createElement('div');node.textContent=error.message;node.style.cssText='position:fixed;inset:0;background:#101820;color:#d9f3f5;padding:32px;font:16px system-ui;z-index:99999';document.body.append(node);state(error.message)});
