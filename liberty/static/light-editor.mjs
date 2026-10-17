export async function graphicsAvailable(win){
 try{const gl=win.document.createElement('canvas').getContext('webgl2');if(gl){gl.getExtension('WEBGL_lose_context')?.loseContext();return true}}catch{}
 // WebGPU can be exposed even when every hardware adapter is unavailable.
 try{return !!(await win.navigator.gpu?.requestAdapter())}catch{return false}
}
export function lightFormat(name){
 if(/\.(txt|md)$/i.test(name))return 'text';
 if(/\.html?$/i.test(name))return 'html';
 throw Error('O modo leve abre e salva TXT, Markdown e HTML. Para DOCX e outros formatos, use o editor completo em um navegador com WebGL2.');
}
export function mountLightEditor(win,{onSave,onState,demo=false}){
 const doc=win.document;
 const make=(tag,text,attrs={})=>{const element=doc.createElement(tag);if(text)element.textContent=text;for(const [name,value]of Object.entries(attrs))element.setAttribute(name,value);return element};
 const stylesheet=make('link',null,{rel:'stylesheet',href:'./__liberty/light-editor.css'});doc.head.append(stylesheet);
 const title=make('h1','Documentos · modo leve');
 const note=make('p','Edição de texto e formatação básica, sem GPU. Suporta TXT, Markdown e HTML; não reproduz os recursos e formatos completos do WordCraft.');
 const name=make('input',null,{value:'documento.html','aria-label':'Nome do documento',maxlength:'160'});
 const area=make('div',null,{class:'light-document',contenteditable:'true',role:'textbox','aria-label':'Conteúdo do documento','aria-multiline':'true',spellcheck:'true'});
 const info=make('p','Digite no documento para começar.',{class:'light-status',role:'status','aria-live':'polite'});
 const status=text=>{info.textContent=text;onState(text)};
 const toolbar=make('div',null,{class:'light-toolbar',role:'toolbar','aria-label':'Formatação e arquivo'});
 const action=(text,run)=>{const button=make('button',text,{type:'button'});button.addEventListener('click',run);toolbar.append(button);return button};
 for(const [label,command]of [['Negrito','bold'],['Itálico','italic'],['Sublinhar','underline'],['Lista','insertUnorderedList']]){
  const button=action(label,()=>{area.focus();doc.execCommand(command,false)});button.addEventListener('mousedown',event=>event.preventDefault());
 }
 if(!demo)action('Abrir TXT/HTML',async()=>{
  try{
   const [handle]=await win.showOpenFilePicker({types:[{description:'Texto e HTML',accept:{'text/plain':['.txt','.md'],'text/html':['.html','.htm']}}]});
   const file=await handle.getFile();const format=lightFormat(file.name);
   if(file.size>2*1024*1024)throw Error('O modo leve abre documentos de até 2 MiB.');
   const text=await file.text();
   // HTML is imported as text, never as active markup or remote resources.
   area.textContent=format==='html'?new win.DOMParser().parseFromString(text,'text/html').body.textContent:text;
   name.value=file.name;status('Arquivo aberto no modo leve. HTML é importado como texto.');area.focus();
  }catch(error){if(error.name!=='AbortError')status(error.message)}
 });
 const save=action(demo?'Baixar cópia':'Salvar no Drive',async()=>{
  try{
   const filename=name.value.trim(),format=lightFormat(filename);save.disabled=true;
   const content=format==='text'?area.innerText:'<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Documento</title><body>'+area.innerHTML+'</body></html>';
   await onSave(new Blob([content],{type:format==='text'?'text/plain;charset=utf-8':'text/html;charset=utf-8'}),filename);
   status(demo?'Cópia baixada. A demonstração não salva no servidor.':'Salvo no Drive');
  }catch(error){status('Não foi possível salvar: '+error.message)}finally{save.disabled=false}
 });
 area.addEventListener('paste',event=>{event.preventDefault();doc.execCommand('insertText',false,event.clipboardData?.getData('text/plain')||'')});
 area.addEventListener('drop',event=>{event.preventDefault();status('Use o botão Abrir TXT/HTML para importar um documento.')});
 area.addEventListener('input',()=>{info.textContent='Alterações não salvas. Use '+(demo?'Baixar cópia.':'Salvar no Drive.')});
 if(demo)area.textContent='Experimente o Liberty Office\n\nEste documento é um exemplo temporário. Selecione um trecho para formatar ou digite suas próprias ideias.\n\nNenhum arquivo é enviado ao servidor.';
 const heading=make('header',null,{class:'light-heading'});heading.append(title,note,name);
 const sheet=make('main',null,{class:'light-sheet'});sheet.append(area);
 doc.body.replaceChildren(heading,toolbar,sheet,info);doc.body.className='light-editor';
 doc.documentElement.dataset.libertyState='ready';doc.documentElement.dataset.libertyMode='light';
 status('Modo leve pronto. TXT/HTML com edição básica; salvamento manual.');
}
