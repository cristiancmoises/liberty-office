import {msg,text} from './i18n.mjs';;

export function deferNativePreloads(doc){
 const links=[...doc.querySelectorAll('link[data-liberty-rel][data-liberty-href]')];
 let restored=false;
 return ()=>{
  if(restored)return;restored=true;
  for(const link of links){
   link.setAttribute('href',link.getAttribute('data-liberty-href'));
   link.setAttribute('rel',link.getAttribute('data-liberty-rel'));
   link.removeAttribute('data-liberty-href');link.removeAttribute('data-liberty-rel');
  }
 };
}

// A canvas exists in the original HTML before WASM starts. Only the upstream
// loading indicator disappearing means its graphical runner initialized.
export function watchEditorRuntime(win,onState){
 const loading=win.document.querySelector('[id$="_loading"], #loading');
 const initialText=loading?.textContent;
 let initialized=false,ready=false,failed=false,timer;
 const report=(phase,text)=>onState(phase,text);
 const fail=text=>{if(failed)return;failed=true;win.clearTimeout(timer);observer.disconnect();report('error',text)};
 const graphics=text(msg('O editor não conseguiu iniciar. Verifique se WebGL2 está disponível neste navegador. Se a GPU não estiver disponível, use outro navegador para o editor completo. Seus arquivos continuam no Drive.'));
 const loadingError=()=>text(msg('Falha ao carregar os arquivos do editor. Confira a conexão e tente abrir o aplicativo novamente. Seus arquivos continuam no Drive.'));
 // Classify only known graphics evidence. Never expose raw exception text,
 // which may contain a private document name or an authenticated runtime URL.
 const isGraphics=value=>/webgl|webgpu|wgpu|no suitable adapter|gpu surface|graphics context/i.test(String(value||''));
 const check=()=>{
  if(ready||failed)return;
  if(loading?.isConnected&&loading.textContent!==initialText&&/failed|error|panic|not supported/i.test(loading.textContent||'')){fail(isGraphics(loading.textContent)?graphics:loadingError());return}
  const canvas=win.document.querySelector('canvas');
  const hidden=loading&&(!loading.isConnected||loading.hidden||win.getComputedStyle(loading).display==='none');
  // PdfCraft has no loading element. eframe installs the focusable canvas
  // after initialization; wait for both that and the module completion event.
  if(canvas&&(hidden||(!loading&&initialized&&canvas.hasAttribute('tabindex')))){
   ready=true;win.clearTimeout(timer);observer.disconnect();
   report('ready',text(msg('Editor pronto. Clique na área de trabalho para editar. Salve pelo menu Arquivo → Salvar/Exportar.')));
  }
 };
 const started=()=>{initialized=true;check()};
 const error=event=>{if(!ready)fail(isGraphics(event?.message||event?.reason?.message)?graphics:loadingError())};
 const lost=()=>fail(ready?text(msg('O contexto gráfico do editor foi perdido. Os arquivos já exportados não foram alterados. Reabra o aplicativo após recuperar o suporte gráfico.')):graphics);
 const observer=new win.MutationObserver(check);
 observer.observe(win.document,{subtree:true,childList:true,attributes:true,characterData:true});
 win.addEventListener('TrunkApplicationStarted',started);
 win.addEventListener('error',error);
 win.addEventListener('unhandledrejection',error);
 win.addEventListener('webglcontextcreationerror',lost,true);
 win.addEventListener('webglcontextlost',lost,true);
 timer=win.setTimeout(()=>fail(text(msg('O editor demorou mais que o esperado para iniciar. Confira a conexão e tente abrir o aplicativo novamente.'))),120000);
 report('loading',text(msg('Iniciando o aplicativo… O primeiro carregamento pode levar alguns instantes.')));
 return ()=>{observer.disconnect();win.clearTimeout(timer);win.removeEventListener('TrunkApplicationStarted',started);win.removeEventListener('error',error);win.removeEventListener('unhandledrejection',error);win.removeEventListener('webglcontextcreationerror',lost,true);win.removeEventListener('webglcontextlost',lost,true)};
}
