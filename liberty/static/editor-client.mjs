import {msg,text,getLanguage,setLanguage} from './i18n.mjs';;
// The portal owns credentials and Drive decisions. Editors get only this bounded protocol.
export function validHandshake(event,{source,origin,nonce}){
 return event.source===source&&event.origin===origin&&event.data?.type==='liberty.ready'&&event.data.nonce===nonce&&
  typeof event.data.documentId==='string'&&/^[A-Za-z0-9_-]{8,64}$/.test(event.data.documentId);
}
export function validateExport(data,maxBytes){
 return data?.type==='export'&&typeof data.id==='string'&&/^export-[0-9]{1,9}$/.test(data.id)&&
  typeof data.name==='string'&&data.name.length>0&&data.name.length<=180&&
  Object.prototype.toString.call(data.buffer)==='[object ArrayBuffer]'&&data.buffer.byteLength<=maxBytes&&
  Object.keys(data).every(k=>['type','id','name','buffer'].includes(k));
}
export function canReconnectEditor(owner,session){return session?.state==='full'&&session.user?.id===owner}
export function connectEditor(frame,config,{onExport,onState=()=>{},onBackup=()=>{},maxBytes=104857600}){
 const env=frame.ownerDocument.defaultView;let port=null,disposed=false,active=0,readyResolve,readyReject;
 const documents=new Set();
 const ready=new Promise((resolve,reject)=>{readyResolve=resolve;readyReject=reject});
 ready.catch(()=>{});
 const timeout=env.setTimeout(()=>{if(!port){readyReject(Error(text(msg('O adaptador do editor não respondeu.'))));onState(text(msg('Falha de conexão com o editor. Confira a origem de edição e preserve o arquivo original.')))}},45000);
 const handshake=event=>{
  if(disposed||!validHandshake(event,{...config,source:frame.contentWindow})||documents.has(event.data.documentId))return;
  documents.add(event.data.documentId);port?.close();
  const channel=new env.MessageChannel(),connection=channel.port1;port=connection;
  connection.onmessage=async e=>{
   if(disposed||port!==connection)return;
   const data=e.data;
   if(data?.type==='state'&&typeof data.text==='string'){onState(data.text.slice(0,500));return}
   if(data?.type==='offer-ack'){onState(text(msg('Arquivo oferecido. No editor, escolha Arquivo → Abrir.')));return}
   if(!validateExport(data,maxBytes)){if(data?.type==='export'&&typeof data.id==='string')connection.postMessage({type:'result',id:data.id,ok:false,error:text(msg('Exportação inválida ou acima do limite.'))});return}
   if(active>=2){connection.postMessage({type:'result',id:data.id,ok:false,error:text(msg('Aguarde o salvamento em andamento.'))});return}
   active++;const blob=new Blob([data.buffer],{type:'application/octet-stream'});onState(text(msg('Salvando no Drive…')));
   try{await onExport(blob,data.name);if(!disposed&&port===connection){connection.postMessage({type:'result',id:data.id,ok:true});onState(text(msg('Salvo no Drive')))}}
   catch(error){let recovered=false;try{onBackup(blob,data.name);recovered=true}catch{}
    if(!disposed&&port===connection){connection.postMessage({type:'result',id:data.id,ok:false,error:error.message,recovered});
     onState(text(msg('Não salvo no Drive: {0} Preserve a cópia local.',error.message)))}
   }finally{active--}
  };
  connection.start();frame.contentWindow.postMessage({type:'liberty.connect',nonce:config.nonce,documentId:event.data.documentId},config.origin,[channel.port2]);
  connection.postMessage({type:'language',language:getLanguage()});
  env.clearTimeout(timeout);readyResolve();onState(text(msg('Conexão segura estabelecida. Iniciando o aplicativo…')));
 };
 env.addEventListener('message',handshake);
 return {
  setLanguage(language){if(['en','pt-BR'].includes(language))port?.postMessage({type:'language',language})},
  async offer(blob,name){await ready;if(disposed)throw Error(text(msg('Editor fechado.')));const buffer=await blob.arrayBuffer();
   if(buffer.byteLength>maxBytes)throw Error(text(msg('Arquivo acima do limite de envio ao editor.')));
   port.postMessage({type:'offer',name,buffer},[buffer]);
  },
  dispose(){disposed=true;env.clearTimeout(timeout);env.removeEventListener('message',handshake);port?.close();readyReject(Error(text(msg('Editor fechado.'))))}
 };
}
