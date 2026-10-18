import {msg,text} from './i18n.mjs';;
import {validateDemoPaste} from './demo-policy.mjs';
export function disableDemoImports(win,notify){
 const denied=()=>{notify(text(msg('Na demonstração, use os exemplos ou digite no editor. A importação de arquivos está desativada.')));throw new DOMException(text(msg('Importação desativada na demonstração.')),'NotAllowedError')};
 const open=win.showOpenFilePicker,directory=win.showDirectoryPicker;
 win.showOpenFilePicker=async()=>denied();win.showDirectoryPicker=async()=>denied();
 const click=win.HTMLInputElement.prototype.click;
 win.HTMLInputElement.prototype.click=function(){if(this.type==='file'){notify(text(msg('Importação de arquivos desativada na demonstração.')));return}return click.call(this)};
 const picker=win.HTMLInputElement.prototype.showPicker;
 if(picker)win.HTMLInputElement.prototype.showPicker=function(){if(this.type==='file')return denied();return picker.call(this)};
 const block=event=>{if(event.type==='drop'||event.type==='dragover'||event.target?.type==='file'||event.clipboardData?.files?.length){event.preventDefault();event.stopImmediatePropagation();if(event.type!=='dragover')notify(text(msg('Importação de arquivos desativada na demonstração.')))}};
 for(const name of ['click','drop','dragover','paste'])win.addEventListener(name,block,true);
 let stopped=false;
 return ()=>{
  if(stopped)return;stopped=true;
  for(const name of ['click','drop','dragover','paste'])win.removeEventListener?.(name,block,true);
  win.HTMLInputElement.prototype.click=click;if(picker)win.HTMLInputElement.prototype.showPicker=picker;
  if(open)win.showOpenFilePicker=open;else delete win.showOpenFilePicker;
  if(directory)win.showDirectoryPicker=directory;else delete win.showDirectoryPicker;
 };
}

export function installDemoImports(win,{budget,policy,notify,onFiles=null}){
 const prototype=win.HTMLInputElement.prototype,click=prototype.click,picker=prototype.showPicker;
 const open=win.showOpenFilePicker,directory=win.showDirectoryPicker;
 const approved=new WeakSet(),busy=new WeakSet(),pickers=new Map();let disposed=false;
 const fail=message=>new DOMException(message,'NotAllowedError');
 const deny=()=>fail('Import is not yet qualified for this demo. '+(policy.reason??''));
 const report=error=>notify(error.message);
 const stop=event=>{event.preventDefault();event.stopImmediatePropagation()};
 function extensions(accept=''){
  const tokens=accept.toLowerCase().split(',').map(value=>value.trim()).filter(Boolean);
  const mime=extension=>extension==='.csv'?'text/csv':extension==='.tsv'?'text/tab-separated-values':/\.html?$/.test(extension)?'text/html':'text/plain';
  return policy.extensions.filter(extension=>!tokens.length||tokens.some(token=>token===extension||token===mime(extension)||token==='text/*'||token==='*/*'||token==='application/octet-stream'));
 }
 function prepare(input){
  if(!policy.qualified)throw deny();
  if(input.webkitdirectory||input.hasAttribute?.('webkitdirectory'))throw fail('Directory imports are disabled in the demo.');
  const allowed=extensions(input.accept||'');if(!allowed.length)throw fail('This picker does not accept a qualified demo format.');
  input.accept=allowed.join(',');input.multiple=!!input.multiple&&!!policy.multiple;
 }
 function emit(target,event){approved.add(event);target.dispatchEvent(event)}
 async function selection(input){
  if(busy.has(input))return;busy.add(input);
  try{
   prepare(input);
   const files=Array.from(input.files||[]);
   if(!input.multiple&&files.length>1)throw fail('Choose one file for this editor.');
   const accepted=await budget.admit(files,policy);if(disposed)return;
   const transfer=new win.DataTransfer();for(const file of accepted)transfer.items.add(file);input.files=transfer.files;
   emit(input,new win.Event('input',{bubbles:true}));emit(input,new win.Event('change',{bubbles:true}));
  }catch(error){input.value='';pickers.get(input)?.reject(error);report(error)}
  finally{busy.delete(input)}
 }
 async function transfer(event,data){
  try{
   if(!policy.qualified)throw deny();
   if(Array.from(data?.items||[]).some(item=>item.webkitGetAsEntry?.()?.isDirectory))throw fail('Directory imports are disabled in the demo.');
   const selected=Array.from(data?.files||[]);
   if(selected.length>1&&!policy.multiple)throw fail('Choose one file for this editor.');
   const files=await budget.admit(selected,policy);if(disposed)return;
   if(onFiles){await onFiles(files);return}
   const clean=new win.DataTransfer();for(const file of files)clean.items.add(file);
   const options={bubbles:true,cancelable:true};let forwarded;
   if(event.type==='paste')forwarded=new win.ClipboardEvent('paste',{...options,clipboardData:clean});
   else forwarded=new win.DragEvent('drop',{...options,dataTransfer:clean,clientX:event.clientX,clientY:event.clientY});
   emit(event.target,forwarded);
  }catch(error){report(error)}
 }
 function receive(event){
  if(disposed||approved.has(event))return;
  const input=event.target?.type==='file'?event.target:null;
  if((event.type==='click')&&input){try{prepare(input)}catch(error){stop(event);report(error)}return}
  if((event.type==='input'||event.type==='change')&&input){stop(event);if(event.type==='change')selection(input);return}
  if(event.type==='dragover'){stop(event);return}
  const data=event.type==='paste'?event.clipboardData:event.dataTransfer;
  if(event.type==='drop'||event.type==='paste'&&(data?.files?.length||Array.from(data?.items||[]).some(item=>item.kind==='file'))){
   stop(event);transfer(event,data);
  }else if(event.type==='paste'){
   try{
    const plain=validateDemoPaste(data?.getData?.('text/plain')||data?.getData?.('text')||'',policy);
    // Standard light-mode text controls paste plain text themselves. Replaying
    // an untrusted ClipboardEvent would suppress that native default action.
    if(policy.kind==='light'&&['INPUT','TEXTAREA'].includes(event.target?.tagName))return;
    stop(event);
    const clean=new win.DataTransfer();clean.setData('text/plain',plain);
    emit(event.target,new win.ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:clean}));
   }catch(error){stop(event);report(error)}
  }
 }
 prototype.click=function(){if(this.type==='file'){try{prepare(this)}catch(error){report(error);return}}return click.call(this)};
 if(picker)prototype.showPicker=function(){if(this.type==='file')prepare(this);return picker.call(this)};
 win.showDirectoryPicker=async()=>{throw fail('Directory imports are disabled in the demo.')};
 win.showOpenFilePicker=async(options={})=>{
  if(disposed)throw fail('The demo editor is closed.');
  if(!policy.qualified)throw deny();
  const input=win.document.createElement('input');input.type='file';input.hidden=true;input.multiple=!!options.multiple&&!!policy.multiple;
  input.accept=(options.types||[]).flatMap(type=>Object.entries(type.accept||{}).flatMap(([mime,extensions])=>extensions.length?extensions:[mime])).join(',');
  prepare(input);
  return new Promise((resolve,reject)=>{
   let done=false;
   const finish=(files,error)=>{
    if(done)return;done=true;pickers.delete(input);input.remove();
    if(error){reject(error);return}
    resolve(files.map(file=>({kind:'file',name:file.name,getFile:async()=>file})));
   };
   pickers.set(input,{reject:error=>finish([],error)});
   input.addEventListener('change',()=>finish(Array.from(input.files||[])),{once:true});
   input.addEventListener('cancel',()=>finish([],new DOMException('Selection cancelled.','AbortError')),{once:true});
   win.document.body.append(input);try{click.call(input)}catch(error){finish([],error)}
  });
 };
 for(const name of ['click','input','change','drop','dragover','paste'])win.addEventListener(name,receive,true);
 return ()=>{
  if(disposed)return;disposed=true;
  for(const name of ['click','input','change','drop','dragover','paste'])win.removeEventListener(name,receive,true);
  for(const pending of pickers.values())pending.reject(new DOMException('The demo editor is closed.','AbortError'));
  prototype.click=click;if(picker)prototype.showPicker=picker;
  if(open)win.showOpenFilePicker=open;else delete win.showOpenFilePicker;
  if(directory)win.showDirectoryPicker=directory;else delete win.showDirectoryPicker;
 };
}
