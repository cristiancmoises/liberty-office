import test from 'node:test';
import assert from 'node:assert/strict';
import {watchEditorRuntime} from '../liberty/static/editor-runtime.mjs';
import * as runtime from '../liberty/static/editor-runtime.mjs';
import {parseHTML} from 'linkedom';

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

test('a missing native module is not mislabeled as a graphics failure',()=>{
 const b=browser();b.loading.textContent='Failed to fetch dynamically imported module';b.mutate();
 assert.equal(b.states.at(-1).phase,'error');
 assert.match(b.states.at(-1).text,/connection/i);
 assert.doesNotMatch(b.states.at(-1).text,/WebGL|GPU/);
});

test('a module rejection is not mislabeled as a graphics failure',()=>{
 const b=browser();b.listeners.get('unhandledrejection')({reason:TypeError('Failed to fetch dynamically imported module')});
 assert.equal(b.states.at(-1).phase,'error');
 assert.doesNotMatch(b.states.at(-1).text,/WebGL|GPU/);
});

test('a failed runner cannot later be announced ready by a DOM mutation',()=>{
 const b=browser();b.listeners.get('error')({message:'WASM blocked'});
 b.loading.isConnected=false;b.mutate();
 assert.equal(b.states.at(-1).phase,'error');
});

test('graphics context loss after initialization reports an error instead of staying ready',()=>{
 const b=browser();b.loading.isConnected=false;b.mutate();
 assert.equal(b.states.at(-1).phase,'ready');
 assert.equal(typeof b.listeners.get('webglcontextlost'),'function');
 b.listeners.get('webglcontextlost')();
 assert.equal(b.states.at(-1).phase,'error');
 assert.match(b.states.at(-1).text,/graphics context was lost/);
});

test('light mode leaves deferred native preloads inert',()=>{
 const {document}=parseHTML('<html><head><link data-liberty-rel="preload" data-liberty-href="./word.wasm" as="fetch" integrity="sha384-wasm"><link data-liberty-rel="modulepreload" data-liberty-href="./word.js" integrity="sha384-module"></head><body></body></html>');
 const restore=runtime.deferNativePreloads(document);
 assert.equal(typeof restore,'function');
 assert.equal(document.querySelector('link[href]'),null);
 assert.equal(document.querySelector('link[rel]'),null);
});

test('full mode restores native preload integrity once without changing styles',()=>{
 const {document}=parseHTML('<html><head><link data-liberty-rel="preload" data-liberty-href="./word.wasm" as="fetch" type="application/wasm" integrity="sha384-wasm" crossorigin="anonymous"><link data-liberty-rel="modulepreload" data-liberty-href="./word.js" integrity="sha384-module"><link rel="stylesheet" href="./editor.css"></head><body></body></html>');
 const restore=runtime.deferNativePreloads(document);restore();
 const links=[...document.querySelectorAll('link')];
 assert.equal(links[0].getAttribute('rel'),'preload');
 assert.equal(links[0].getAttribute('href'),'./word.wasm');
 assert.equal(links[0].getAttribute('integrity'),'sha384-wasm');
 assert.equal(links[0].getAttribute('crossorigin'),'anonymous');
 assert.equal(links[1].getAttribute('rel'),'modulepreload');
 assert.equal(links[1].getAttribute('integrity'),'sha384-module');
 assert.equal(links[2].getAttribute('href'),'./editor.css');
 const before=document.head.innerHTML;restore();assert.equal(document.head.innerHTML,before);
});
