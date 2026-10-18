import test from 'node:test';
import assert from 'node:assert/strict';
import {acquireDemoSession,listenDemoController} from '../liberty/static/demo-session.mjs';

const portalOrigin='https://office.test',nonce='a'.repeat(32);
const options={portalOrigin,nonce};
const tick=()=>new Promise(setImmediate);

function storage(){
 const values=new Map([['old','temporary data']]);
 return {get length(){return values.size},clear(){values.clear()},removeItem:k=>values.delete(k),setItem:(k,v)=>values.set(k,v),getItem:k=>values.get(k)??null};
}
function locks(){
 const held=new Set();
 return {held,async request(name,settings,callback){
  assert.equal(settings.ifAvailable,true);
  if(held.has(name))return callback(null);
  held.add(name);try{return await callback({name})}finally{held.delete(name)}
 }};
}
function platform(sharedLocks=locks()){
 const events=new Map(),replies=[],databases=new Set(['old-db']),files=new Set(['old-project']),cacheNames=new Set(['effectcraft-old']);
 const failure={},pending=[];let unregistered=false;
 const win={location:{origin:'https://demo-edit.test'},localStorage:storage(),sessionStorage:storage(),
  parent:{postMessage(data,origin){assert.equal(origin,portalOrigin);replies.push(data)}},
  addEventListener(type,listener){events.set(type,listener)},removeEventListener(type,listener){if(events.get(type)===listener)events.delete(type)},
  indexedDB:{databases:async()=>[...databases].map(name=>({name})),deleteDatabase(name){
   const request={};queueMicrotask(()=>{if(failure.blocked){pending.push([name,request]);request.onblocked?.()}else{databases.delete(name);request.onsuccess()}});return request;
  }},
  caches:{keys:async()=>[...cacheNames],delete:async name=>cacheNames.delete(name)},
  navigator:{locks:sharedLocks,storage:{getDirectory:async()=>{
   if(failure.opfs)throw Error('OPFS blocked');
   return {async *keys(){yield* files},async removeEntry(name,settings){assert.equal(settings.recursive,true);files.delete(name)}};
  }},serviceWorker:{controller:null,getRegistrations:async()=>[{
   scope:'https://demo-edit.test/demo/runtime/effectcraft/',unregister:async()=>{unregistered=true;return true}
  }]}}
 };
 return {win,replies,databases,files,cacheNames,failure,locks:sharedLocks,
  get unregistered(){return unregistered},
  unblock(){failure.blocked=false;for(const [name,request] of pending.splice(0)){databases.delete(name);request.onsuccess()}},
  async send(action,requestId='request-00000001',changes={}){
   await events.get('message')?.({source:win.parent,origin:portalOrigin,
    data:{type:'liberty.demo.session',nonce,requestId,action},...changes});
  }};
}

test('second owner cannot clear storage belonging to an active editor',async()=>{
 const p=platform(),session=await acquireDemoSession(p.win,options);
 p.win.localStorage.setItem('project','working');p.databases.add('active-db');p.files.add('active-project');
 await assert.rejects(acquireDemoSession(p.win,{...options,nonce:'b'.repeat(32)}),{name:'DemoSessionBusy'});
 assert.equal(p.win.localStorage.getItem('project'),'working');assert(p.files.has('active-project'));assert(p.databases.has('active-db'));
 await session.finish();assert.equal(p.files.size,0);assert.equal(p.databases.size,0);
 assert.equal(p.locks.held.size,1);
 await assert.rejects(acquireDemoSession(p.win,options),{name:'DemoSessionBusy'});
 session.dispose();await tick();assert.equal(p.locks.held.size,0);
 const next=await acquireDemoSession(p.win,options);next.dispose();await tick();
});

test('sample sessions also require lifetime ownership and clear stale demo data',async()=>{
 const p=platform(),privateData=platform();privateData.win.localStorage.setItem('private','keep');
 const session=await acquireDemoSession(p.win,options);
 assert.equal(p.files.size,0);assert.equal(p.cacheNames.size,0);assert.equal(p.databases.size,0);
 assert.equal(p.win.localStorage.length,0);assert.equal(p.win.sessionStorage.length,0);assert(p.unregistered);
 assert.equal(privateData.win.localStorage.getItem('private'),'keep');assert.equal(privateData.files.size,1);
 await assert.rejects(acquireDemoSession(p.win,options),{name:'DemoSessionBusy'});
 session.dispose();await tick();
});

test('missing locks and blocked browser persistence prevent readiness',async()=>{
 for(const change of [p=>{p.win.navigator.locks=undefined},p=>{p.win.indexedDB.databases=undefined},
  p=>{p.win.indexedDB.databases=async()=>{throw Error('storage blocked')}},p=>{p.failure.opfs=true},p=>{p.win.localStorage.clear=()=>{throw Error('storage blocked')}}]){
  const p=platform();change(p);await assert.rejects(acquireDemoSession(p.win,options));await tick();assert.equal(p.locks.held.size,0);
 }
});

test('cleanup failure retains ownership and never reports a cleared project',async()=>{
 const p=platform(),session=await acquireDemoSession(p.win,options);
 p.databases.add('active-db');p.failure.opfs=true;
 await assert.rejects(session.finish(),/blocked/i);assert.equal(p.locks.held.size,1);
 await assert.rejects(acquireDemoSession(p.win,options),{name:'DemoSessionBusy'});
 p.failure.opfs=false;await session.finish();session.dispose();await tick();
});

test('missing OPFS cleanup blocks a shared origin that may contain older native data',async()=>{
 const p=platform();p.win.navigator.storage={};
 await assert.rejects(acquireDemoSession(p.win,options));await tick();assert.equal(p.locks.held.size,0);
});

test('controller ignores wrong-source, wrong-origin, extra fields and stale nonces',async()=>{
 const p=platform(),controller=listenDemoController(p.win,options);
 await p.send('acquire','request-00000001',{source:{}});
 await p.send('acquire','request-00000002',{origin:'https://untrusted.test'});
 await p.send('acquire','request-00000003',{data:{type:'liberty.demo.session',nonce:'b'.repeat(32),requestId:'request-00000003',action:'acquire'}});
 await p.send('acquire','request-00000004',{data:{type:'liberty.demo.session',nonce,requestId:'request-00000004',action:'acquire',extra:true}});
 assert.equal(p.replies.length,0);assert.equal(p.locks.held.size,0);
 await p.send('acquire');assert.equal(p.replies.at(-1).status,'ready');
 await p.send('clear');assert.equal(p.replies.length,1); // A stale requestId cannot clear current work.
 controller.dispose();await tick();
});

test('clear acknowledgement precedes release, including a sample-only session',async()=>{
 const p=platform(),controller=listenDemoController(p.win,options);
 await p.send('acquire');assert.equal(p.replies.at(-1).status,'ready');
 await p.send('release','request-00000002');assert.equal(p.replies.at(-1).status,'failed');assert.equal(p.locks.held.size,1);
 p.files.add('sample-document');await p.send('clear','request-00000003');
 assert.equal(p.files.size,0);assert.equal(p.replies.at(-1).status,'cleared');assert.equal(p.locks.held.size,1);
 assert.deepEqual(Object.keys(p.replies.at(-1)).sort(),['nonce','requestId','status','type']);
 await p.send('release','request-00000004');await tick();assert.equal(p.locks.held.size,0);
 await p.send('acquire','request-00000005');assert.equal(p.replies.at(-1).status,'failed');
 controller.dispose();
});

test('controller cleanup failure cannot advertise cleared or admit another engine',async()=>{
 const p=platform(),controller=listenDemoController(p.win,options);
 await p.send('acquire');p.databases.add('blocked-db');p.failure.opfs=true;
 await p.send('clear','request-00000002');assert.equal(p.replies.at(-1).status,'failed');
 assert.equal(p.locks.held.size,1);await p.send('release','request-00000003');assert.equal(p.locks.held.size,1);
 await p.send('acquire','request-00000004');assert.equal(p.replies.at(-1).status,'failed');
 await assert.rejects(acquireDemoSession(p.win,options),{name:'DemoSessionBusy'});
 controller.dispose();await tick();
});

test('a blocked deletion stays pending and keeps ownership until actual success',async()=>{
 const p=platform();p.failure.blocked=true;let ready=false;
 const pending=acquireDemoSession(p.win,options).then(session=>{ready=true;return session});
 await tick();assert.equal(ready,false);assert.equal(p.locks.held.size,1);
 await assert.rejects(acquireDemoSession(p.win,options),{name:'DemoSessionBusy'});
 p.unblock();const session=await pending;session.dispose();await tick();
});

test('disposal cannot release a live lock while an uncancellable deletion is pending',async()=>{
 const p=platform(),session=await acquireDemoSession(p.win,options);
 p.databases.add('live-db');p.failure.blocked=true;
 const finishing=session.finish();await tick();session.dispose();await tick();
 assert.equal(p.locks.held.size,1);p.unblock();await finishing;await tick();assert.equal(p.locks.held.size,0);
});

test('controller never acknowledges cleared while a blocked deletion can still run',async()=>{
 const p=platform(),controller=listenDemoController(p.win,options);
 await p.send('acquire');p.databases.add('live-db');p.failure.blocked=true;
 const clearing=p.send('clear','request-00000002');await tick();
 assert.equal(p.replies.at(-1).status,'ready');assert.equal(p.locks.held.size,1);
 p.unblock();await clearing;assert.equal(p.replies.at(-1).status,'cleared');controller.dispose();await tick();
});

test('legacy worker retirement waits for redundancy before deleting its caches',async()=>{
 const p=platform(),listeners=new Set();
 const worker={state:'activated',addEventListener(type,listener){listeners.add(listener)},removeEventListener(type,listener){listeners.delete(listener)}};
 p.win.navigator.serviceWorker.getRegistrations=async()=>[{
  scope:'https://demo-edit.test/demo/runtime/effectcraft/',active:worker,unregister:async()=>true
 }];
 let ready=false;const pending=acquireDemoSession(p.win,options).then(session=>{ready=true;return session});
 await tick();assert.equal(ready,false);assert.equal(p.locks.held.size,1);assert(p.cacheNames.has('effectcraft-old'));
 worker.state='redundant';for(const listener of [...listeners])listener();
 const session=await pending;assert.equal(p.cacheNames.size,0);session.dispose();await tick();
});

test('invalid session configuration rejects without throwing synchronously or touching storage',async()=>{
 const p=platform();let pending;
 assert.doesNotThrow(()=>{pending=acquireDemoSession(p.win,{portalOrigin:'invalid origin',nonce})});
 await assert.rejects(pending);assert.equal(p.locks.held.size,0);assert.equal(p.files.size,1);
});

test('an interrupted legacy-worker retirement cannot silently become a clean new session',async()=>{
 const p=platform();p.win.localStorage.setItem('liberty.demo.retiring-workers','1');
 await assert.rejects(acquireDemoSession(p.win,options),/Close all demo tabs/);
 await tick();assert.equal(p.files.size,1);assert.equal(p.locks.held.size,0);
});
