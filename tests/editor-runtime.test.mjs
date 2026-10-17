import test from 'node:test';
import assert from 'node:assert/strict';
import {watchEditorRuntime} from '../liberty/static/editor-runtime.mjs';

function browser(initialText='Loading WordCraft…'){
 const listeners=new Map(),timers=new Map(),states=[];
 const loading={isConnected:true,textContent:initialText,hidden:false};
 const canvas={width:300,height:150,hasAttribute:()=>false};
 let observe;
 const win={document:{querySelector:selector=>selector==='canvas'?canvas:loading},
  MutationObserver:class{constructor(fn){observe=fn}observe(){}disconnect(){}},
  getComputedStyle:()=>({display:'flex',visibility:'visible'}),
  addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name),
  setTimeout:fn=>{timers.set(timers.size+1,fn);return timers.size},clearTimeout:id=>timers.delete(id)};
 watchEditorRuntime(win,(phase,text)=>states.push({phase,text}));
 return {win,loading,canvas,states,listeners,timers,mutate:()=>observe()};
}
test('the upstream HTML canvas and module event alone do not mark an editor ready',()=>{
 const b=browser();b.listeners.get('TrunkApplicationStarted')();
 assert.equal(b.states.at(-1).phase,'loading');
 b.loading.isConnected=false;b.mutate();
 assert.equal(b.states.at(-1).phase,'ready');
});
test('upstream graphics failure is reported without claiming the canvas is editable',()=>{
 const b=browser();b.loading.textContent='WordCraft failed to start: no suitable adapter';b.mutate();
 assert.equal(b.states.at(-1).phase,'error');assert.match(b.states.at(-1).text,/WebGL2/);
});
test('static hidden troubleshooting text is not mistaken for an upstream failure',()=>{
 const b=browser('Loading PhotoCraft… its files may have failed to download');b.mutate();
 assert.equal(b.states.at(-1).phase,'loading');b.loading.isConnected=false;b.mutate();
 assert.equal(b.states.at(-1).phase,'ready');
});
test('module errors and a stalled startup produce visible status',()=>{
 const b=browser();b.listeners.get('error')({message:'WASM blocked'});
 assert.equal(b.states.at(-1).phase,'error');
 const stalled=browser();[...stalled.timers.values()][0]();
 assert.equal(stalled.states.at(-1).phase,'error');assert.match(stalled.states.at(-1).text,/taking longer/);
});
