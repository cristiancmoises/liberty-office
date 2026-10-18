const OWNER='liberty.demo.owner',ENGINE='liberty.demo.engine',RETIRING='liberty.demo.retiring-workers';
const validNonce=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{24,80}$/.test(value);
const requestId=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{8,80}$/.test(value);
function busy(){const error=Error('Another demo session owns this browser storage.');error.name='DemoSessionBusy';return error}
async function withoutEngine(win,operation){
 return win.navigator.locks.request(ENGINE,{ifAvailable:true},async lock=>{
  if(!lock)throw busy();return operation();
 });
}

async function retireWorkers(win,local){
 if(local.getItem(RETIRING))throw Error('Close all demo tabs and clear this demo site’s data after interrupted worker cleanup.');
 const service=win.navigator.serviceWorker;
 if(!service)return;
 if(service.controller)throw Error('Open a new demo session outside the old worker scope.');
 const registrations=await service.getRegistrations();
 if(!registrations.length)return;
 for(const registration of registrations){
  const scope=new URL(registration.scope);
  if(scope.origin!==win.location.origin||scope.pathname!=='/demo/runtime/effectcraft/')throw Error('Unrecognized demo worker scope.');
 }
 // Keep evidence across controller crashes: unregistering does not stop a
 // worker that still controls another document or retains an open Cache.
 local.setItem(RETIRING,'1');
 const workers=new Set();
 const remember=registration=>{for(const key of ['active','waiting','installing'])if(registration[key])workers.add(registration[key])};
 for(const registration of registrations){remember(registration);await registration.unregister();remember(registration)}
 await Promise.all([...workers].map(worker=>new Promise(resolve=>{
  const check=()=>{if(worker.state==='redundant'){worker.removeEventListener('statechange',check);resolve()}};
  worker.addEventListener('statechange',check);check();
 })));
 local.removeItem(RETIRING);
}

async function clearDemoStorage(win){
 const {localStorage:local,sessionStorage:session,indexedDB:indexed,caches}=win;
 const filesystem=win.navigator.storage;
 if(!local?.clear||!session?.clear||!indexed?.databases||!indexed.deleteDatabase||
    !caches?.keys||!caches.delete||!filesystem?.getDirectory)throw Error('Required demo cleanup APIs are unavailable.');
 await retireWorkers(win,local);
 for(const key of await caches.keys())await caches.delete(key);
 if((await caches.keys()).length)throw Error('Demo cache cleanup did not finish.');
 const requests=(await indexed.databases()).filter(database=>typeof database.name==='string').map(database=>new Promise((resolve,reject)=>{
  const request=indexed.deleteDatabase(database.name);
  request.onsuccess=()=>resolve();
  request.onerror=()=>reject(Error('Demo database cleanup failed.'));
  // onblocked is not completion and cannot cancel deleteDatabase. Keep the
  // promise and lifetime lock pending until the real success/error event.
 }));
 const results=await Promise.allSettled(requests);
 const failed=results.find(result=>result.status==='rejected');
 if(failed)throw failed.reason;
 if((await indexed.databases()).some(database=>typeof database.name==='string'))throw Error('Demo databases changed during cleanup.');
 const root=await filesystem.getDirectory();
 for await(const name of root.keys()){
  try{await root.removeEntry(name,{recursive:true})}catch(error){if(error?.name!=='NotFoundError')throw error}
 }
 for await(const name of root.keys())throw Error('Demo filesystem cleanup did not finish: '+name);
 local.clear();session.clear();
 if(local.length||session.length)throw Error('Demo web storage cleanup did not finish.');
}

export async function acquireDemoSession(win,{portalOrigin,nonce}){
 if(!validNonce(nonce)||new URL(portalOrigin).origin!==portalOrigin||win.location.origin===portalOrigin)
  return Promise.reject(Error('Invalid isolated demo session.'));
 if(!win.navigator.locks?.request)return Promise.reject(Error('Web Locks are required for demo sessions.'));
 return new Promise((resolve,reject)=>{
  win.navigator.locks.request(OWNER,{ifAvailable:true},async lock=>{
   if(!lock){reject(busy());return}
   try{
    await withoutEngine(win,async()=>{await clearDemoStorage(win);win.localStorage.setItem(OWNER,nonce)});
    let release,cleared=false,disposed=false,inflight=null;
    const lifetime=new Promise(done=>{release=done});
    const session={
     finish(){
      if(disposed)return Promise.reject(Error('Demo session has ended.'));
      if(cleared)return Promise.resolve();
      if(inflight)return inflight;
      const operation=withoutEngine(win,()=>clearDemoStorage(win));inflight=operation;
      operation.then(()=>{cleared=true;inflight=null},()=>{inflight=null});
      return operation;
     },
     dispose(){
      if(disposed)return;disposed=true;
      if(inflight)inflight.then(release,release);else release();
     }
    };
    resolve(session);await lifetime;
   }catch(error){reject(error)}
  }).catch(reject);
 });
}

// This second lease survives loss of the sibling controller. The owner marker
// rejects delayed starts from a previous session; it contains no document data.
export async function acquireDemoEngine(win,{portalOrigin,nonce}){
 if(!validNonce(nonce)||new URL(portalOrigin).origin!==portalOrigin||win.location.origin===portalOrigin||!win.navigator.locks?.request)
  throw Error('Invalid demo engine owner.');
 return new Promise((resolve,reject)=>{
  win.navigator.locks.request(ENGINE,{ifAvailable:true},async lock=>{
   if(!lock)throw busy();
   if(win.localStorage.getItem(OWNER)!==nonce)throw Error('Demo engine owner has changed.');
   let release;const lifetime=new Promise(done=>{release=done});
   resolve({dispose(){release()}});await lifetime;
  }).catch(reject);
 });
}

export function listenDemoController(win,{portalOrigin,nonce}){
 if(!validNonce(nonce)||new URL(portalOrigin).origin!==portalOrigin)throw Error('Invalid demo controller.');
 const seen=new Set();let phase='idle',session=null,disposed=false;
 async function receive(event){
  if(disposed||event.source!==win.parent||event.origin!==portalOrigin)return;
  const data=event.data;
  if(!data||Array.isArray(data)||data.type!=='liberty.demo.session'||data.nonce!==nonce||
     !requestId(data.requestId)||!['acquire','clear','release'].includes(data.action)||
     Object.keys(data).length!==4||!Object.keys(data).every(key=>['type','nonce','requestId','action'].includes(key))||seen.has(data.requestId))return;
  seen.add(data.requestId);if(seen.size>32)seen.delete(seen.values().next().value);
  const reply=status=>{if(!disposed)win.parent.postMessage({type:'liberty.demo.session',nonce,requestId:data.requestId,status},portalOrigin)};
  if(['closed','failed'].includes(phase)){reply('failed');return}
  if(['acquiring','clearing'].includes(phase)){reply('busy');return}
  if(data.action==='acquire'){
   if(phase==='active'){reply('ready');return}
   if(phase!=='idle'){reply('failed');return}
   phase='acquiring';
   try{
    session=await acquireDemoSession(win,{portalOrigin,nonce});
    if(disposed){session.dispose();return}
    phase='active';reply('ready');
   }catch(error){phase='failed';reply(error?.name==='DemoSessionBusy'?'busy':'failed')}
  }else if(data.action==='clear'){
   if(phase==='cleared'){reply('cleared');return}
   if(!['active','cleanup-failed'].includes(phase)){reply('failed');return}
   phase='clearing';
   try{await session.finish();phase='cleared';reply('cleared')}
   catch{phase='cleanup-failed';reply('failed')}
  }else{
   if(phase!=='cleared'){reply('failed');return}
   session.dispose();phase='closed';reply('cleared');
  }
 }
 win.addEventListener('message',receive);
 return {dispose(){disposed=true;win.removeEventListener('message',receive);session?.dispose()}};
}

function connectChannel(win,{frame,origin,nonce,timeoutMs=15000},type,actions,statuses){
 if(!validNonce(nonce)||new URL(origin).origin!==origin)throw Error('Invalid demo channel.');
 const pending=new Map();let disposed=false;
 function receive(event){
  if(disposed||event.source!==frame.contentWindow||event.origin!==origin)return;
  const data=event.data;
  if(!data||data.type!==type||data.nonce!==nonce||!requestId(data.requestId)||!statuses.includes(data.status)||
   Object.keys(data).length!==4||!Object.keys(data).every(key=>['type','nonce','requestId','status'].includes(key)))return;
  const operation=pending.get(data.requestId);if(!operation)return;
  pending.delete(data.requestId);win.clearTimeout(operation.timer);operation.resolve(data.status);
 }
 win.addEventListener('message',receive);
 return {
  async request(action){
   if(disposed)throw Error('Demo channel is closed.');
   if(!actions.includes(action))throw Error('Invalid demo action.');
   if(pending.size)throw Error('A demo operation is still pending.');
   const id=win.crypto.randomUUID();
   return new Promise((resolve,reject)=>{
    const timer=win.setTimeout(()=>{
     pending.delete(id);const error=Error('Demo operation did not finish. Ownership has not been released.');
     error.name='DemoSessionTimeout';reject(error);
    },timeoutMs);
    pending.set(id,{resolve,reject,timer});
    try{frame.contentWindow.postMessage({type,nonce,requestId:id,action},origin)}
    catch(error){pending.delete(id);win.clearTimeout(timer);reject(error)}
   });
  },
  dispose(){
   disposed=true;win.removeEventListener('message',receive);
   for(const operation of pending.values()){win.clearTimeout(operation.timer);operation.reject(Error('Demo channel is closed.'))}
   pending.clear();
  }
 };
}

export const connectDemoSession=(win,options)=>connectChannel(win,options,'liberty.demo.session',['acquire','clear','release'],['ready','busy','cleared','failed']);
export const connectDemoEngine=(win,options)=>connectChannel(win,options,'liberty.demo.engine',['start','stop'],['started','stopped','failed']);
