import {listenDemoController} from './demo-session.mjs';

const config=JSON.parse(document.getElementById('__liberty-controller').textContent);
const controller=listenDemoController(window,{portalOrigin:config.portalOrigin,nonce:location.hash.slice(1)});
window.addEventListener('pagehide',()=>controller.dispose(),{once:true});
