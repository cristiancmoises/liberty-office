import {msg,bindText} from './i18n.mjs';

// Resize the real editor viewport; never scale a canvas or its input coordinates.
export function viewControls(target){
 const doc=target.ownerDocument,controls=doc.createElement('div');controls.className='view-controls';
 const focus=doc.createElement('button');focus.type='button';focus.setAttribute('aria-pressed','false');bindText(focus,msg('Modo foco'));
 focus.addEventListener('click',()=>{const enabled=target.classList.toggle('is-focused');focus.setAttribute('aria-pressed',String(enabled));bindText(focus,msg(enabled?'Sair do foco':'Modo foco'))});
 controls.append(focus);
 if(target.requestFullscreen){
  const fullscreen=doc.createElement('button');fullscreen.type='button';bindText(fullscreen,msg('Tela cheia'));
  fullscreen.addEventListener('click',async()=>{try{if(doc.fullscreenElement===target)await doc.exitFullscreen();else await target.requestFullscreen()}catch{bindText(fullscreen,msg('Tela cheia indisponível'))}});
  const changed=()=>{if(!target.isConnected){doc.removeEventListener('fullscreenchange',changed);return}bindText(fullscreen,msg(doc.fullscreenElement===target?'Sair da tela cheia':'Tela cheia'))};
  doc.addEventListener('fullscreenchange',changed);controls.append(fullscreen);
 }
 return controls;
}
