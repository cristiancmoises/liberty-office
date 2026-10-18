import {msg,text,bindText,bindAttribute,getLanguage,ownedMessage} from './i18n.mjs';
export async function graphicsAvailable(win){
 try{const gl=win.document.createElement('canvas').getContext('webgl2');if(gl){gl.getExtension('WEBGL_lose_context')?.loseContext();return true}}catch{}
 // WebGPU can be exposed even when every hardware adapter is unavailable.
 try{return !!(await win.navigator.gpu?.requestAdapter())}catch{return false}
}
// A basic text editor is not WordCraft. Keep that choice explicit when the
// browser cannot provide graphics, and leave the original full runner available.
export async function selectEditorMode(win,{appId,light=false,onState,onSelect}){
 if(appId==='wordcraft'&&light){onSelect('light');return}
 if(await graphicsAvailable(win)){onSelect('full');return}
 const doc=win.document,previous=[...doc.body.childNodes],previousClass=doc.body.className;
 const stylesheet=doc.createElement('link');stylesheet.rel='stylesheet';stylesheet.href='./__liberty/light-editor.css';doc.head.append(stylesheet);
 const make=(tag,message)=>{const node=doc.createElement(tag);if(message)bindText(node,message);return node};
 const panel=make('main');panel.className='editor-compatibility';
 const title=msg('O editor completo precisa de acesso gráfico');
 panel.append(make('h1',title),make('p',msg('WebGL2 e um adaptador WebGPU não estão disponíveis neste navegador. O aplicativo completo não foi substituído por outro editor.')));
 const steps=make('ol');
 for(const message of [
  msg('No Chrome ou Chromium, confira a aceleração gráfica em Configurações → Sistema e o diagnóstico em chrome://gpu.'),
  msg('Se a aceleração estiver ativada, verifique o driver de vídeo e reinicie o navegador após corrigir o problema. Outros navegadores no mesmo computador podem usar o mesmo driver.'),
  msg('Um site não pode habilitar WebGL bloqueado pelo navegador ou reparar um driver. Não é necessário desativar o sandbox nem a segurança do navegador.'),
 ])steps.append(make('li',message));
 panel.append(steps,make('p',msg('Seus arquivos originais não foram alterados. Feche este editor para voltar ao Drive ou concluir e limpar a demonstração.')));
 const actions=make('div');actions.className='compatibility-actions';let selected=false;
 const action=(message,mode)=>{
  const button=make('button',message);button.type='button';button.addEventListener('click',()=>{
   if(selected)return;selected=true;doc.body.replaceChildren(...previous);doc.body.className=previousClass;stylesheet.remove();onSelect(mode);
  });actions.append(button);
 };
 action(msg('Tentar editor completo'),'full');
 if(appId==='wordcraft'){
  panel.append(make('p',msg('Alternativa opcional: o editor básico de texto funciona sem GPU, mas abre e salva apenas TXT, Markdown e HTML. Ele não é o WordCraft completo e não abre DOCX.')));
  action(msg('Abrir editor básico de texto'),'light');
 }
 panel.append(actions);doc.body.replaceChildren(panel);doc.body.className='editor-compatibility-page';
 doc.documentElement.dataset.libertyState='blocked';onState(text(title));
}
export function lightFormat(name){
 if(/\.(txt|md)$/i.test(name))return 'text';
 if(/\.html?$/i.test(name))return 'html';
 throw Error(msg('O modo leve abre e salva TXT, Markdown e HTML. Para DOCX e outros formatos, use o editor completo em um navegador com WebGL2.'));
}
export function lightHTMLText(doc,html){
 // Parsing boundary only: template contents remain detached and inert. Never
 // insert these nodes into the active document; the caller receives text only.
 const template=doc.createElement('template');template.innerHTML=html;
 const skip=new Set(['HEAD','TITLE','SCRIPT','STYLE','TEMPLATE','IFRAME','OBJECT','EMBED']);
 const blocks=new Set(['ADDRESS','ARTICLE','ASIDE','BLOCKQUOTE','DD','DETAILS','DIV','DL','DT','FIELDSET','FIGCAPTION','FIGURE','FOOTER','FORM','H1','H2','H3','H4','H5','H6','HEADER','HR','LI','MAIN','NAV','OL','P','PRE','SECTION','SUMMARY','TABLE','TBODY','TFOOT','THEAD','TR','UL']);
 let result='',pending='';const stack=[template.content];
 const boundary=separator=>{if(separator==='\n'||!pending)pending=separator};
 const append=value=>{if(!value)return;if(pending&&result&&!result.endsWith('\n'))result+=pending;pending='';result+=value};
 // Iterative traversal also bounds call-stack use for deeply nested input.
 while(stack.length){
  const node=stack.pop();
  if(typeof node==='string'){boundary(node);continue}
  if(node.nodeType===3){append(node.nodeValue);continue}
  const tag=node.tagName?.toUpperCase();if(skip.has(tag))continue;
  if(tag==='BR'){append('\n');continue}
  const separator=blocks.has(tag)?'\n':['TD','TH'].includes(tag)?'\t':'';
  if(separator){boundary(separator);stack.push(separator)}
  for(let child=node.lastChild;child;child=child.previousSibling)stack.push(child);
 }
 return result;
}
export function mountLightEditor(win,{onSave,onState,demo=false,admit=null}){
 const doc=win.document;
 const make=(tag,value,attrs={})=>{const element=doc.createElement(tag);if(value)bindText(element,value);for(const [name,value]of Object.entries(attrs))bindAttribute(element,name,value);return element};
 const stylesheet=make('link',null,{rel:'stylesheet',href:'./__liberty/light-editor.css'});doc.head.append(stylesheet);
 const title=make('h1',msg('Documentos · modo leve'));
 const note=make('p',msg('Edição de texto e formatação básica, sem GPU. Suporta TXT, Markdown e HTML; não reproduz os recursos e formatos completos do WordCraft.'));
 const name=make('input',null,{value:getLanguage()==='pt-BR'?'documento.html':'document.html','aria-label':msg('Nome do documento'),maxlength:'160'});
 const area=make('div',null,{class:'light-document',contenteditable:'true',role:'textbox','aria-label':msg('Conteúdo do documento'),'aria-multiline':'true',spellcheck:'true'});
 const info=make('p',msg('Digite no documento para começar.'),{class:'light-status',role:'status','aria-live':'polite'});
 const status=value=>{value=ownedMessage(value);bindText(info,value);onState(text(value))};
 const formatNote=make('p',msg('TXT e Markdown são salvos como texto puro, sem formatação. Negrito, itálico, sublinhado e listas não são preservados. Use HTML para exportar a formatação.'),{class:'light-format-note',role:'note'});
 const updateFormatNote=()=>{formatNote.hidden=!/\.(txt|md)$/i.test(name.value.trim())};updateFormatNote();
 let revision=0;
 const unsaved=()=>msg('Alterações não salvas. Use {0}',demo?msg('Baixar cópia.'):msg('Salvar no Drive.'));
 const dirty=()=>{revision++;status(unsaved())};
 name.addEventListener('input',()=>{updateFormatNote();dirty()});
 const toolbar=make('div',null,{class:'light-toolbar',role:'toolbar','aria-label':msg('Formatação e arquivo')});
 const action=(text,run)=>{const button=make('button',text,{type:'button'});button.addEventListener('click',run);toolbar.append(button);return button};
 for(const [label,command]of [[msg('Negrito'),'bold'],[msg('Itálico'),'italic'],[msg('Sublinhar'),'underline'],[msg('Lista'),'insertUnorderedList']]){
  const button=action(label,()=>{const before=area.innerHTML,version=revision;area.focus();doc.execCommand(command,false);if(before!==area.innerHTML&&version===revision)dirty()});button.addEventListener('mousedown',event=>event.preventDefault());
 }
 async function openFile(file){
  try{
   const format=lightFormat(file.name);
   if(file.size>2*1024*1024)throw Error(msg('O modo leve abre documentos de até 2 MiB.'));
   const text=await file.text();
   // HTML is imported as text, never as active markup or remote resources.
   area.textContent=format==='html'?lightHTMLText(doc,text):text;
   name.value=file.name;revision++;updateFormatNote();status(msg('Arquivo aberto no modo leve. HTML é importado como texto.'));area.focus();
  }catch(error){if(error.name!=='AbortError')status(error.message)}
 }
 if(!demo||admit)action(msg('Abrir TXT/HTML'),async()=>{
  try{
   const options={types:[{description:text(msg('Texto e HTML')),accept:{'text/plain':['.txt','.md'],'text/html':['.html','.htm']}}]};
   const [file]=admit?await admit(options):[await(await win.showOpenFilePicker(options))[0].getFile()];
   if(file)await openFile(file);
  }catch(error){if(error.name!=='AbortError')status(error.message)}
 });
 const save=action(demo?msg('Baixar cópia'):msg('Salvar no Drive'),async()=>{
  try{
   const filename=name.value.trim(),format=lightFormat(filename),version=revision;save.disabled=true;
   const content=format==='text'?area.innerText:'<!doctype html><html lang="'+getLanguage()+'"><meta charset="utf-8"><title>Document</title><body>'+area.innerHTML+'</body></html>';
   await onSave(new Blob([content],{type:format==='text'?'text/plain;charset=utf-8':'text/html;charset=utf-8'}),filename);
   if(version!==revision)status(unsaved());
   else if(format==='text')status(demo?msg('Download de texto puro iniciado, sem formatação. Nada é salvo no servidor.'):msg('Salvo no Drive como texto puro, sem formatação.'));
   else status(demo?msg('Download iniciado. Confira os downloads do navegador. Nada é salvo no servidor.'):msg('Salvo no Drive'));
  }catch(error){status(msg('Não foi possível salvar: {0}',error.message))}finally{save.disabled=false}
 });
 area.addEventListener('paste',event=>{event.preventDefault();doc.execCommand('insertText',false,event.clipboardData?.getData('text/plain')||'')});
 area.addEventListener('drop',event=>{event.preventDefault();status(msg('Use o botão Abrir TXT/HTML para importar um documento.'))});
 area.addEventListener('input',dirty);
 if(demo)area.textContent=msg('Experimente o Liberty Office\n\nEste documento é um exemplo temporário. Selecione um trecho para formatar ou digite suas próprias ideias.\n\nNenhum arquivo é enviado ao servidor.');
 const heading=make('header',null,{class:'light-heading'});heading.append(title,note,name,formatNote);
 const sheet=make('main',null,{class:'light-sheet'});sheet.append(area);
 doc.body.replaceChildren(heading,toolbar,sheet,info);doc.body.className='light-editor';
 doc.documentElement.dataset.libertyState='ready';doc.documentElement.dataset.libertyMode='light';
 status(msg('Modo leve pronto. TXT/HTML com edição básica; salvamento manual.'));
 return {openFile};
}
