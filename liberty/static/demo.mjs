const launcher=document.querySelector('#demo-launcher'),editor=document.querySelector('#demo-editor'),holder=document.querySelector('#demo-frame'),status=document.querySelector('#demo-status');
let current=null;
function open(app){
 const frame=document.createElement('iframe');frame.title=app.name+' — demonstração';
 frame.sandbox='allow-scripts allow-same-origin allow-downloads';frame.referrerPolicy='no-referrer';
 frame.src=app.url;current={frame,origin:new URL(app.url).origin};
 document.querySelector('#demo-name').textContent=app.name;status.textContent='Carregando '+app.name+'…';
 holder.replaceChildren(frame);launcher.hidden=true;editor.hidden=false;document.querySelector('#demo-close').focus();
}
document.querySelector('#demo-close').addEventListener('click',()=>{if(!confirm('Sair da demonstração? As alterações não são salvas no servidor.'))return;holder.replaceChildren();current=null;editor.hidden=true;launcher.hidden=false;document.querySelector('#demo-apps button')?.focus()});
window.addEventListener('message',event=>{if(current&&event.source===current.frame.contentWindow&&event.origin===current.origin&&event.data?.type==='liberty.demo.state'&&typeof event.data.text==='string')status.textContent=event.data.text.slice(0,500)});
try{
 const response=await fetch('/demo/apps');if(!response.ok)throw Error('Não foi possível carregar a demonstração.');
 const {apps}=await response.json();
 for(const app of apps){
  const button=document.createElement('button');button.className='app-card';button.title=app.name;button.disabled=!app.installed;
  const icon=document.createElement('span');icon.className='app-icon '+app.id;icon.textContent=app.monogram;
  const name=document.createElement('h2');name.textContent=app.name;
  const description=document.createElement('p');description.textContent=app.installed?app.description:'Indisponível neste servidor';
  button.append(icon,name,description);button.addEventListener('click',()=>open(app));document.querySelector('#demo-apps').append(button);
 }
 document.querySelector('#demo-message').textContent='Selecione um aplicativo para começar. Nenhum login é necessário.';
}catch(error){document.querySelector('#demo-message').textContent=error.message}
