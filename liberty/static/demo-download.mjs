import {createWritable} from './bridge.mjs';
import {msg,text} from './i18n.mjs';

const MAX_BYTES=100*1024*1024;
const requestId=value=>typeof value==='string'&&/^demo-[A-Za-z0-9_-]{8,64}$/.test(value);
const filename=value=>typeof value==='string'&&value.length>0&&value.length<=180&&value.trim()===value&&
 !/[\x00-\x1f\x7f/\\<>:"|?*]/.test(value)&&value!=='.'&&value!=='..';
const mimeType=value=>typeof value==='string'&&value.length<=128&&/^[\w.+-]+\/[\w.+-]+(?:;[\w=.+ -]+)*$/.test(value);
const invalid=()=>Error(text(msg('Exportação inválida ou acima do limite.')));
const started=()=>text(msg('Download iniciado. Confira os downloads do navegador. Nada é salvo no servidor.'));

export function validateDemoExport(data,maxBytes=MAX_BYTES){
 return !!data&&data.type==='liberty.demo.export'&&requestId(data.id)&&filename(data.name)&&mimeType(data.mime)&&
  data.buffer instanceof ArrayBuffer&&data.buffer.byteLength>0&&data.buffer.byteLength<=Math.min(maxBytes,MAX_BYTES)&&
  Object.keys(data).length===5&&Object.keys(data).every(key=>['type','id','name','mime','buffer'].includes(key));
}

// This receiver has no account or Drive capabilities. Only the active demo frame
// may ask its portal to initiate a local download; an ACK is not proof of disk save.
export function connectDemoDownloads(win,{frame,origin,onState=()=>{},maxBytes=MAX_BYTES}){
 const recent=new Set(),urls=new Map();let disposed=false,active=false;
 const revoke=url=>{win.clearTimeout(urls.get(url));urls.delete(url);win.URL.revokeObjectURL(url)};
 function receive(event){
  if(disposed||event.source!==frame.contentWindow||event.origin!==origin)return;
  const data=event.data;
  if(data?.type!=='liberty.demo.export'||!requestId(data.id))return;
  const reply=(ok,error)=>event.source.postMessage({type:'liberty.demo.export-result',id:data.id,ok,...(error?{error}:{})},origin);
  if(!validateDemoExport(data,maxBytes)){reply(false,invalid().message);return}
  if(recent.has(data.id))return;
  if(active){reply(false,text(msg('Aguarde o download em andamento.')));return}
  active=true;recent.add(data.id);if(recent.size>32)recent.delete(recent.values().next().value);
  let url;
  try{
   url=win.URL.createObjectURL(new win.Blob([data.buffer],{type:'application/octet-stream'}));
   const link=win.document.createElement('a');link.href=url;link.download=data.name;link.hidden=true;
   win.document.body.append(link);try{link.click()}finally{link.remove()}
   urls.set(url,win.setTimeout(()=>revoke(url),60000));
   while(urls.size>2)revoke(urls.keys().next().value);
   reply(true);onState(started());
  }catch{if(url)revoke(url);const error=text(msg('Não foi possível iniciar o download.'));reply(false,error);onState(error)}
  finally{active=false}
 }
 win.addEventListener('message',receive);
 return {dispose(){disposed=true;win.removeEventListener('message',receive);for(const url of urls.keys())revoke(url);recent.clear()}};
}

export function installDemoExports(win,{portalOrigin,onState=()=>{},maxBytes=MAX_BYTES,timeoutMs=15000}){
 maxBytes=Math.min(maxBytes,MAX_BYTES);
 let disposed=false,busy=false,pending=null,trackedBytes=0;
 const blobs=new Map(),create=win.URL.createObjectURL.bind(win.URL),revoke=win.URL.revokeObjectURL.bind(win.URL);
 const click=win.HTMLAnchorElement.prototype.click,savePicker=win.showSaveFilePicker;
 const forget=url=>{const blob=blobs.get(url);if(blob){trackedBytes-=blob.size;blobs.delete(url)}};
 function finish(error){
  if(!pending)return;
  win.clearTimeout(pending.timer);const {resolve,reject}=pending;pending=null;
  if(error)reject(error);else resolve();
 }
 function receive(event){
  const data=event.data;
  if(event.source!==win.parent||event.origin!==portalOrigin||data?.type!=='liberty.demo.export-result'||data.id!==pending?.id||
   typeof data.ok!=='boolean'||Object.keys(data).some(key=>!['type','id','ok','error'].includes(key))||
   (data.error!==undefined&&(typeof data.error!=='string'||data.error.length>500)))return;
  finish(data.ok?null:Error(data.error||text(msg('Não foi possível iniciar o download.'))));
 }
 async function exportBlob(blob,name){
  if(disposed)throw Error(text(msg('Editor fechado.')));
  if(busy)throw Error(text(msg('Aguarde o download em andamento.')));
  if(!blob||typeof blob.arrayBuffer!=='function'||!Number.isSafeInteger(blob.size)||blob.size<1||blob.size>maxBytes||!filename(name))throw invalid();
  busy=true;
  try{
   const buffer=await blob.arrayBuffer(),id='demo-'+win.crypto.randomUUID(),mime=blob.type||'application/octet-stream';
   if(disposed)throw Error(text(msg('Editor fechado.')));
   const message={type:'liberty.demo.export',id,name,mime,buffer};
   if(!validateDemoExport(message,maxBytes)||buffer.byteLength!==blob.size)throw invalid();
   await new Promise((resolve,reject)=>{
    const timer=win.setTimeout(()=>finish(Error(text(msg('O portal não confirmou o início do download.')))),timeoutMs);
    pending={id,resolve,reject,timer};
    try{win.parent.postMessage(message,portalOrigin,[buffer])}catch(error){finish(error)}
   });
   onState(started());
  }finally{busy=false}
 }
 function forward(anchor){
  if(!anchor.download||!anchor.href.startsWith('blob:'))return false;
  const blob=blobs.get(anchor.href);
  if(blob)exportBlob(blob,anchor.download).catch(error=>onState(error.message));else onState(invalid().message);
  return true;
 }
 win.URL.createObjectURL=blob=>{
  const url=create(blob);
  if(Number.isSafeInteger(blob?.size)&&blob.size>0&&blob.size<=maxBytes){
   blobs.set(url,blob);trackedBytes+=blob.size;
   while(blobs.size>64||trackedBytes>maxBytes)forget(blobs.keys().next().value);
  }
  return url;
 };
 win.URL.revokeObjectURL=url=>{forget(url);return revoke(url)};
 win.HTMLAnchorElement.prototype.click=function(){if(!forward(this))return click.call(this)};
 const intercept=event=>{const anchor=event.target?.closest?.('a[download]');if(anchor&&forward(anchor)){event.preventDefault();event.stopImmediatePropagation()}};
 win.addEventListener('click',intercept,true);win.addEventListener('message',receive);
 win.showSaveFilePicker=async(options={})=>{
  const name=options.suggestedName||'export.bin';
  return {kind:'file',name,createWritable:async()=>createWritable(blob=>exportBlob(blob,name),maxBytes)};
 };
 function dispose(){
  if(disposed)return;disposed=true;finish(Error(text(msg('Editor fechado.'))));
  win.removeEventListener('message',receive);win.removeEventListener('click',intercept,true);win.removeEventListener('pagehide',dispose);
  win.URL.createObjectURL=create;win.URL.revokeObjectURL=revoke;win.HTMLAnchorElement.prototype.click=click;
  if(savePicker)win.showSaveFilePicker=savePicker;else delete win.showSaveFilePicker;
  blobs.clear();trackedBytes=0;
 }
 win.addEventListener('pagehide',dispose);
 return {exportBlob,dispose};
}
