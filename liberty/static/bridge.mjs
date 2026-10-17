import {msg,text} from './i18n.mjs';;
/* Liberty's adapter operates outside the original upstream bundles. */
export function saveTarget(opened,name){
 const same=opened?.owned && opened.name===name;
 return same?{method:'PUT',url:`/api/files/${opened.id}/content`,headers:{'If-Match':opened.etag}}:
  {method:'POST',url:'/api/files?'+new URLSearchParams({name,...(opened?.owned&&opened.parent?{parent:opened.parent}:{})}),headers:{}};
}
export function serialSaver(fn){
 let tail=Promise.resolve();
 return (...args)=>{const result=tail.then(()=>fn(...args));tail=result.catch(()=>{});return result};
}
export function createWritable(onClose,maxBytes=104857600){
 let data=new Uint8Array(),position=0,closed=false;
 const check=()=>{if(closed)throw Error('stream closed')};
 const isBlob=value=>value&&typeof value.arrayBuffer==='function'&&typeof value.size==='number';
 const resize=size=>{
  if(!Number.isSafeInteger(size)||size<0||size>maxBytes)throw Error(text(msg('Exportação excede o limite de envio.')));
  if(size!==data.length){const next=new Uint8Array(size);next.set(data.subarray(0,size));data=next}
 };
 return {
  async write(input){
   check();
   if(input&&typeof input==='object'&&!isBlob(input)&&!ArrayBuffer.isView(input)&&!(input instanceof ArrayBuffer)&&'type' in input){
    if(input.type==='seek')return this.seek(input.position);
    if(input.type==='truncate')return this.truncate(input.size);
    if(input.type!=='write')throw Error(text(msg('Operação de escrita desconhecida.')));
    if(input.position!==undefined)await this.seek(input.position);
    input=input.data;
   }
   let bytes;
   if(isBlob(input))bytes=new Uint8Array(await input.arrayBuffer());
   else if(typeof input==='string')bytes=new TextEncoder().encode(input);
   else if(ArrayBuffer.isView(input))bytes=new Uint8Array(input.buffer,input.byteOffset,input.byteLength);
   else bytes=new Uint8Array(input);
   const end=position+bytes.length;
   if(end>data.length)resize(end);
   data.set(bytes,position);position=end;
  },
  async seek(value){check();if(!Number.isSafeInteger(value)||value<0||value>maxBytes)throw Error(text(msg('Posição inválida.')));position=value},
  async truncate(size){check();resize(size);position=Math.min(position,size)},
  async close(){check();await onClose(new Blob([data]));closed=true;data=new Uint8Array()},
  async abort(){closed=true;data=new Uint8Array()}
 };
}
export function attachBridge(win,{onExport,onState=()=>{},onBackup=null,maxBytes=104857600}){
 let offered=null;
 const urls=new Map(),savers=[];
 const exportFile=serialSaver(async(blob,name)=>{
  onState('Salvando no Drive…');
  try{const result=await onExport(blob,name);onState('Salvo no Drive');return result}
  catch(error){onState(text(msg('Falha ao salvar no Drive. Preserve a cópia local.')));throw error}
 });
 const originalCreate=win.URL.createObjectURL.bind(win.URL),originalRevoke=win.URL.revokeObjectURL.bind(win.URL);
 const anchorClick=win.HTMLAnchorElement.prototype.click;
 const inputClick=win.HTMLInputElement.prototype.click;
 function backup(blob,name){
  if(onBackup){onBackup(blob,name);return}
  const url=originalCreate(blob),a=win.document.createElement('a');a.href=url;a.download=name;
  anchorClick.call(a);setTimeout(()=>originalRevoke(url),30000);
 }
 win.URL.createObjectURL=blob=>{const url=originalCreate(blob);urls.set(url,blob);return url};
 win.URL.revokeObjectURL=url=>{urls.delete(url);return originalRevoke(url)};
 win.HTMLAnchorElement.prototype.click=function(){
  const blob=urls.get(this.href),name=this.download;
  const result=anchorClick.call(this); // Keep the upstream download as a local recovery copy.
  if(blob&&name)exportFile(blob,name).catch(error=>onState(error.message));
  return result;
 };
 const savePicker=win.showSaveFilePicker,openPicker=win.showOpenFilePicker;
 // Rust's web adapters choose this at Save time. Closing resolves only after Drive accepts it.
 win.showSaveFilePicker=async(options={})=>{
  const name=options.suggestedName||'exportacao.bin';
  return {kind:'file',name,createWritable:async()=>createWritable(async blob=>{
   try{await exportFile(blob,name)}catch(error){if(!error.recovered)backup(blob,name);throw error}
  },maxBytes)};
 };
 win.HTMLInputElement.prototype.click=function(){
  if(this.type==='file'&&offered){
   const file=offered;offered=null;const input=this;
   queueMicrotask(()=>{
    try{const dt=new win.DataTransfer();dt.items.add(file);input.files=dt.files;
     input.dispatchEvent(new win.Event('input',{bubbles:true}));input.dispatchEvent(new win.Event('change',{bubbles:true}));onState(text(msg('Arquivo entregue ao editor')))}
    catch(error){onState(text(msg('Use o download do Drive e o botão Abrir do editor. {0}',error.message)))}
   });
   return;
  }
  return inputClick.call(this);
 };
 win.showOpenFilePicker=async options=>{
  if(offered){const file=offered;offered=null;return [{kind:'file',name:file.name,getFile:async()=>file}]}
  // Native File System Access rejects cross-origin iframes. A user-activated
  // input works here and returns the small handle surface used by upstream.
  return new Promise((resolve,reject)=>{
   const input=win.document.createElement('input');input.type='file';input.hidden=true;input.multiple=!!options?.multiple;
   input.accept=(options?.types||[]).flatMap(type=>Object.entries(type.accept||{}).flatMap(([mime,extensions])=>[mime,...extensions])).join(',');
   let done=false;
   const finish=files=>{if(done)return;done=true;input.remove();
    if(!files.length){reject(new DOMException(text(msg('Seleção cancelada.')),'AbortError'));return}
    resolve(files.map(file=>({kind:'file',name:file.name,getFile:async()=>file})));
   };
   input.addEventListener('change',()=>finish(Array.from(input.files||[]).slice(0,input.multiple?undefined:1)),{once:true});
   input.addEventListener('cancel',()=>finish([]),{once:true});win.document.body.append(input);
   try{inputClick.call(input)}catch(error){input.remove();reject(error)}
  });
 };
 return {
  offer(blob,name){offered=new win.File([blob],name,{type:blob.type||'application/octet-stream'});onState(text(msg('No editor, escolha Arquivo → Abrir para carregar {0}',name)))},
  dispose(){
   win.URL.createObjectURL=originalCreate;win.URL.revokeObjectURL=originalRevoke;
   win.HTMLAnchorElement.prototype.click=anchorClick;win.HTMLInputElement.prototype.click=inputClick;
   if(savePicker)win.showSaveFilePicker=savePicker;else delete win.showSaveFilePicker;
   if(openPicker)win.showOpenFilePicker=openPicker;else delete win.showOpenFilePicker;
   urls.clear();offered=null;
  }
 };
}

export function createDriveSaver(getOpened,send){
 const saved=new Map();
 const save=serialSaver(async(blob,name)=>{
  const target=saveTarget(saved.get(name)||getOpened(),name);
  const result=await send(target,blob);
  saved.set(name,{...result,owned:true});
  return result;
 });
 save.reset=()=>saved.clear();
 return save;
}
