import test from 'node:test';
import assert from 'node:assert/strict';
import {disableDemoImports} from '../liberty/static/demo-guard.mjs';
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
