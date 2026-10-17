import {english} from './translations.mjs';

export const languageFromURL=url=>new URL(url,'http://localhost').searchParams.get('lang')==='pt-BR'?'pt-BR':'en';
export function languageURL(url,language){const target=new URL(url,'http://localhost');target.searchParams.set('lang',language==='pt-BR'?'pt-BR':'en');return target.href}
let language=languageFromURL(globalThis.location?.href||'http://localhost');
const bindings=new Map(),listeners=new Set();
export const getLanguage=()=>language;
export const isMessage=value=>value instanceof Message;
class Message{
 constructor(key,args){this.key=key;this.args=args}
 toString(){return text(this)}
}
export const msg=(key,...args)=>new Message(key,args);
export function ownedMessage(value){if(isMessage(value))return value;const key=Object.hasOwn(english,value)?value:Object.keys(english).find(key=>english[key]===value);return key?msg(key):value}
export function text(value){
 if(typeof value==='function')return text(value());
 if(!isMessage(value))return String(value??'');
 const template=language==='pt-BR'?value.key:(english[value.key]??value.key);
 return template.replace(/\{(\d+)\}/g,(_,index)=>text(value.args[Number(index)]));
}
export function bindText(node,value){
 node.textContent=text(value);
 if(isMessage(value))bindings.set(node,{...bindings.get(node),value});else bindings.delete(node);
 return node;
}
export function bindAttribute(node,name,value){
 node.setAttribute(name,text(value));
 if(isMessage(value)){let binding=bindings.get(node);if(!binding){binding={};bindings.set(node,binding)}(binding.attrs??={})[name]=value}
}
export function onLanguageChange(listener){listeners.add(listener);return()=>listeners.delete(listener)}
export function setLanguage(value){
 language=value==='pt-BR'?'pt-BR':'en';
 for(const [node,binding]of bindings){
  if(!node.isConnected){bindings.delete(node);continue}
  if(binding.value)node.textContent=text(binding.value);
  for(const [name,message]of Object.entries(binding.attrs||{}))node.setAttribute(name,text(message));
 }
 for(const listener of listeners)if(listener(language)===false)listeners.delete(listener);
}
export function installLanguage(win){
 setLanguage(languageFromURL(win.location.href));
 win.document.documentElement.lang=language;
 onLanguageChange(value=>{win.document.documentElement.lang=value;win.history.replaceState(null,'',languageURL(win.location.href,value))});
 for(const node of win.document.querySelectorAll('[data-i18n]'))bindText(node,msg(node.dataset.i18n));
}
export function languageSelector(doc){
 const label=doc.createElement('label');label.className='language-selector';
 const caption=doc.createElement('span');bindText(caption,msg('Idioma'));label.append(caption);
 const select=doc.createElement('select');select.setAttribute('aria-label','Language / Idioma');
 for(const [value,label]of [['en','English'],['pt-BR','Português (Brasil)']]){const option=doc.createElement('option');option.value=value;option.textContent=label;select.append(option)}
 select.value=language;select.addEventListener('change',()=>setLanguage(select.value));
 onLanguageChange(value=>{if(!select.isConnected)return false;select.value=value});label.append(select);return label;
}
