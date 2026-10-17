import test from 'node:test';import assert from 'node:assert/strict';
import {clearEditorIdentity} from '../liberty/static/editor-storage.mjs';
function storage(values={}){const map=new Map(Object.entries(values));return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),clear:()=>map.clear()}}
function platform(previous='alice'){
 const files=new Set(['effectcraft','lightcraft']);const deleted=[];
 return {local:storage({'liberty.identity':previous,'liberty.opfs.identity':previous}),session:storage({secret:'alice'}),
  indexed:{databases:async()=>[{name:'alice-db'}],deleteDatabase(){const r={};queueMicrotask(()=>{deleted.push('indexed');r.onsuccess()});return r}},
  filesystem:{getDirectory:async()=>({async *keys(){yield* files},async removeEntry(name,opts){assert.equal(opts.recursive,true);deleted.push(name);files.delete(name)}})},files,deleted};
}
test('identity switch clears OPFS and IndexedDB before marking the new identity',async()=>{
 const p=platform();await clearEditorIdentity('bob',p);
 assert.equal(p.files.size,0);assert.deepEqual(p.deleted.sort(),['effectcraft','indexed','lightcraft']);
 assert.equal(p.local.getItem('liberty.identity'),'bob');assert.equal(p.local.getItem('liberty.opfs.identity'),'bob');assert.equal(p.session.getItem('secret'),null);
 await clearEditorIdentity('bob',p);assert.equal(p.deleted.length,3);
});
test('failed filesystem cleanup rejects and never marks the new account ready',async()=>{
 const p=platform();p.filesystem.getDirectory=async()=>({async *keys(){yield 'locked'},async removeEntry(){throw Error('busy')}});
 await assert.rejects(clearEditorIdentity('bob',p),/busy/);assert.notEqual(p.local.getItem('liberty.identity'),'bob');assert.notEqual(p.local.getItem('liberty.opfs.identity'),'bob');
});
test('OPFS becoming available later still clears files left by a previous account',async()=>{
 const p=platform(),filesystem=p.filesystem;p.filesystem=null;await clearEditorIdentity('bob',p);assert.equal(p.files.size,2);
 p.filesystem=filesystem;await clearEditorIdentity('bob',p);assert.equal(p.files.size,0);
});
