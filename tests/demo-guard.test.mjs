import test from 'node:test';
import assert from 'node:assert/strict';
import {disableDemoImports,installDemoImports} from '../liberty/static/demo-guard.mjs';
import {createDemoBudget,demoPolicy} from '../liberty/static/demo-policy.mjs';
import {setLanguage} from '../liberty/static/i18n.mjs';
test('demo rejects file and directory pickers, file inputs and file drops',async()=>{
 const notices=[],events=new Map();let native=0;
 class Input{click(){native++}showPicker(){native++}}
 const win={HTMLInputElement:Input,addEventListener:(name,fn)=>events.set(name,fn)};
 disableDemoImports(win,text=>notices.push(text));
 await assert.rejects(win.showOpenFilePicker(),{name:'NotAllowedError'});
 await assert.rejects(win.showDirectoryPicker(),{name:'NotAllowedError'});
 const input=new Input();input.type='file';input.click();assert.throws(()=>input.showPicker(),{name:'NotAllowedError'});
 assert.equal(native,0);input.type='text';input.click();assert.equal(native,1);
 for(const type of ['click','drop','paste']){
  let prevented=false,stopped=false;
  events.get(type)({type,target:{type:'file'},clipboardData:{files:[{}]},preventDefault(){prevented=true},stopImmediatePropagation(){stopped=true}});
  assert.equal(prevented,true);assert.equal(stopped,true);
 }
 let prevented=false;events.get('paste')({type:'paste',target:{},clipboardData:{files:[]},preventDefault(){prevented=true}});
 assert.equal(prevented,false);assert.ok(notices.length>=5);
});

function platform(){
 const listeners=new Map(),created=[],notices=[];let native=0;
 class Transfer{
  constructor(){this.files=[];this.items={add:file=>this.files.push(file)};this.text=new Map()}
  setData(type,value){this.text.set(type==='text'?'text/plain':type,value)}
  getData(type){return this.text.get(type==='text'?'text/plain':type)||''}
 }
 class Input{
  constructor(){this.type='file';this.files=[];this.listeners=new Map();this.multiple=false}
  click(){native++}showPicker(){native++}remove(){}
  addEventListener(type,fn){this.listeners.set(type,fn)}
  dispatchEvent(event){
   Object.defineProperty(event,'target',{value:this,configurable:true});
   let stopped=false;Object.defineProperty(event,'stopImmediatePropagation',{value:()=>{stopped=true},configurable:true});
   win.emit(event);if(!stopped)this.listeners.get(event.type)?.(event);return !stopped;
  }
 }
 const win={HTMLInputElement:Input,DataTransfer:Transfer,Event,DOMException,
  DragEvent:class extends Event{constructor(type,options){super(type,options);this.dataTransfer=options.dataTransfer}},
  ClipboardEvent:class extends Event{constructor(type,options){super(type,options);this.clipboardData=options.clipboardData}},
  document:{body:{append(){}},createElement(){const input=new Input();created.push(input);return input}},
  addEventListener(type,fn){if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(fn)},
  removeEventListener(type,fn){listeners.get(type)?.delete(fn)},
  emit(event){
   let stopped=false;const stop=event.stopImmediatePropagation.bind(event);
   Object.defineProperty(event,'stopImmediatePropagation',{value:()=>{stopped=true;stop()},configurable:true});
   for(const fn of listeners.get(event.type)||[]){fn(event);if(stopped)break}
  },dispatchEvent(event){win.emit(event)}
 };
 return {win,notices,created,get native(){return native}};
}
const tick=()=>new Promise(setImmediate);
const selected=(name='notes.txt',value='safe')=>new File([value],name,{type:'text/plain'});

test('blocked import reasons and admission errors follow the selected interface language',async()=>{
 setLanguage('pt-BR');
 try{
  const p=platform(),stop=installDemoImports(p.win,{budget:createDemoBudget(),policy:demoPolicy('pdfcraft'),notify:value=>p.notices.push(value)});
  await assert.rejects(p.win.showOpenFilePicker(),error=>/Fluxos PDF/.test(error.message)&&!error.message.includes('Import is'));
  assert(p.notices.some(value=>value.includes('Fluxos PDF')));
  stop();
  const q=platform(),dispose=installDemoImports(q.win,{budget:createDemoBudget(),policy:demoPolicy('wordcraft'),notify:value=>q.notices.push(value)});
  const pending=q.win.showOpenFilePicker(),input=q.created[0];input.files=[selected('unsupported.docx')];input.dispatchEvent(new Event('change'));
  await assert.rejects(pending);assert(q.notices.some(value=>value.includes('formato de arquivo não é compatível')));dispose();
 }finally{setLanguage('en')}
});

test('picker and input selections reserve once before exposing files to native handlers',async()=>{
 const p=platform(),budget=createDemoBudget(),stop=installDemoImports(p.win,{budget,policy:demoPolicy('wordcraft'),notify:value=>p.notices.push(value)});
 const pending=p.win.showOpenFilePicker({types:[{accept:{'text/plain':['.txt']}}]});
 const input=p.created[0],file=selected();input.files=[file];input.dispatchEvent(new Event('input'));input.dispatchEvent(new Event('change'));
 const handles=await pending;assert.equal(await handles[0].getFile(),file);assert.deepEqual(budget.usage,{files:1,bytes:4});
 assert.equal(handles[0].createWritable,undefined);assert.equal(handles[0].getFileHandle,undefined);
 let nativeChanges=0;const second=new p.win.HTMLInputElement();second.accept='.txt';second.addEventListener('change',()=>nativeChanges++);
 second.files=[selected('second.txt')];second.dispatchEvent(new Event('input'));second.dispatchEvent(new Event('change'));await tick();
 assert.equal(nativeChanges,1);assert.equal(budget.usage.files,2);
 second.files=[selected('unsafe.txt','PK\x03\x04')];second.dispatchEvent(new Event('change'));await tick();
 assert.equal(nativeChanges,1);assert.equal(second.value,'');assert.equal(budget.usage.files,3);stop();
});

test('file drops and pastes share the same cumulative budget and strip unrelated payloads',async()=>{
 const p=platform(),budget=createDemoBudget(),received=[];
 const stop=installDemoImports(p.win,{budget,policy:demoPolicy('wordcraft'),notify:value=>p.notices.push(value),onFiles:files=>received.push(files)});
 for(let n=0;n<11;n++){
  const transfer=new p.win.DataTransfer();transfer.items.add(selected('selection-'+n+'.txt'));
  const event=new p.win.DragEvent(n%2?'paste':'drop',{dataTransfer:transfer});
  if(event.type==='paste')event.clipboardData=transfer;
  p.win.emit(event);await tick();
 }
 assert.equal(received.length,10);assert.equal(budget.usage.files,10);assert(p.notices.some(value=>/10 files/.test(value)));
 const directory=new p.win.DragEvent('drop',{dataTransfer:{files:[],items:[{webkitGetAsEntry:()=>({isDirectory:true})}]}});
 p.win.emit(directory);await tick();assert.equal(received.length,10);assert(p.notices.some(value=>/Director/.test(value)));
 stop();
});

test('directory and incompatible pickers stay denied; disposal restores original methods',async()=>{
 const p=platform(),click=p.win.HTMLInputElement.prototype.click,picker=p.win.HTMLInputElement.prototype.showPicker;
 const stop=installDemoImports(p.win,{budget:createDemoBudget(),policy:demoPolicy('wordcraft'),notify:value=>p.notices.push(value)});
 await assert.rejects(p.win.showDirectoryPicker(),{name:'NotAllowedError'});
 await assert.rejects(p.win.showOpenFilePicker({types:[{accept:{'image/png':['.png']}}]}),/format/i);
 const input=new p.win.HTMLInputElement();input.webkitdirectory=true;input.click();assert.equal(p.native,0);
 stop();stop();assert.equal(p.win.HTMLInputElement.prototype.click,click);assert.equal(p.win.HTMLInputElement.prototype.showPicker,picker);
 assert.equal(p.win.showOpenFilePicker,undefined);assert.equal(p.win.showDirectoryPicker,undefined);
});

test('a single-file native editor cannot import a multi-file selection',async()=>{
 const p=platform(),budget=createDemoBudget();
 const stop=installDemoImports(p.win,{budget,policy:demoPolicy('wordcraft'),notify:value=>p.notices.push(value)});
 const input=new p.win.HTMLInputElement();input.multiple=true;input.files=[selected('one.txt'),selected('two.txt')];
 input.dispatchEvent(new Event('change'));await tick();
 assert.equal(budget.usage.files,0);assert(p.notices.some(value=>/one file/.test(value)));stop();
});

test('native clipboard receives only bounded plain text, never rich flavors or unqualified imports',()=>{
 const p=platform(),budget=createDemoBudget(),received=[];
 const stop=installDemoImports(p.win,{budget,policy:demoPolicy('wordcraft'),notify:value=>p.notices.push(value)});
 p.win.addEventListener('paste',event=>received.push({plain:event.clipboardData.getData('text').slice(0,60),html:event.clipboardData.getData('text/html')}));
 for(const value of ['Plain text','<svg><rect/></svg>','x'.repeat(500_001)]){
  const data=new p.win.DataTransfer();data.setData('text/plain',value);data.setData('text/html','<img src="https://not-requested.invalid/">');
  const event=new p.win.ClipboardEvent('paste',{clipboardData:data});Object.defineProperty(event,'target',{value:p.win});p.win.emit(event);
 }
 assert.deepEqual(received,[{plain:'Plain text',html:''}]);assert.equal(budget.usage.files,0);assert.equal(p.notices.length,2);stop();
});
