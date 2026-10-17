import {msg,text} from './i18n.mjs';;
// A canvas exists in the original HTML before WASM starts. Only the upstream
// loading indicator disappearing means its graphical runner initialized.
export function watchEditorRuntime(win,onState){
 const loading=win.document.querySelector('[id$="_loading"], #loading');
 const initialText=loading?.textContent;
 let initialized=false,ready=false,failed=false,timer;
 const report=(phase,text)=>onState(phase,text);
 const fail=text=>{if(ready||failed)return;failed=true;win.clearTimeout(timer);report('error',text)};
 const graphics=text(msg('O editor não conseguiu iniciar. Verifique se WebGL2 está disponível neste navegador. Se a GPU não estiver disponível, use outro navegador para o editor completo. Seus arquivos continuam no Drive.'));
 const check=()=>{
  if(ready)return;
  if(loading?.isConnected&&loading.textContent!==initialText&&/failed|error|panic|not supported/i.test(loading.textContent||'')){fail(graphics);return}
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
 const error=()=>fail(text(msg('Falha ao carregar o editor. Confira a conexão e o suporte a WebAssembly/WebGL2. Feche e abra o aplicativo para tentar novamente. Seus arquivos continuam no Drive.')));
 const observer=new win.MutationObserver(check);
 observer.observe(win.document,{subtree:true,childList:true,attributes:true,characterData:true});
 win.addEventListener('TrunkApplicationStarted',started);
 win.addEventListener('error',error);
 win.addEventListener('unhandledrejection',error);
 timer=win.setTimeout(()=>fail(text(msg('O editor demorou mais que o esperado para iniciar. Confira a conexão e o suporte a WebGL2. Feche e abra o aplicativo para tentar novamente.'))),120000);
 report('loading',text(msg('Iniciando o aplicativo… O primeiro carregamento pode levar alguns instantes.')));
 return ()=>{observer.disconnect();win.clearTimeout(timer);win.removeEventListener('TrunkApplicationStarted',started);win.removeEventListener('error',error);win.removeEventListener('unhandledrejection',error)};
}
