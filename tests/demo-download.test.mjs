import test from 'node:test';
import assert from 'node:assert/strict';
import {validateDemoExport,connectDemoDownloads,installDemoExports} from '../liberty/static/demo-download.mjs';

const portalOrigin='https://office.example',demoOrigin='https://demo.example';
const payload=(patch={})=>({type:'liberty.demo.export',id:'demo-12345678',name:'document.html',mime:'text/html;charset=utf-8',buffer:new TextEncoder().encode('real document').buffer,...patch});
function browser(){
 const listeners=new Map(),blobs=new Map(),downloads=[],revoked=[];let sequence=0;
 class Anchor{click(){downloads.push({name:this.download,blob:blobs.get(this.href)})}remove(){}}
 const win={Blob,crypto,HTMLAnchorElement:Anchor,setTimeout,clearTimeout,
  URL:{createObjectURL(blob){const url='blob:fixture-'+(++sequence);blobs.set(url,blob);return url},revokeObjectURL(url){revoked.push(url);blobs.delete(url)}},
  document:{createElement(){return new Anchor()},body:{append(){}}},
  addEventListener(type,fn){if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(fn)},
  removeEventListener(type,fn){listeners.get(type)?.delete(fn)},
  emit(type,event){for(const listener of listeners.get(type)||[])listener(event)},downloads,revoked};
 return win;
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));

test('demo export accepts only bounded binary bytes, safe names, MIME and exact fields',()=>{
 assert.equal(validateDemoExport(payload(),100),true);
 for(const patch of [{buffer:new ArrayBuffer(0)},{buffer:new ArrayBuffer(101)},{buffer:new Uint8Array(2)},
  {buffer:{byteLength:2}},{name:''},{name:'../private.html'},{name:'folder\\file'},{name:'bad\nname'},
  {name:'x'.repeat(181)},{mime:'text/html\r\nHeader: injected'},{mime:'javascript:alert(1)'},
  {mime:'x'.repeat(129)},{id:'../../id'},{type:'export'},{url:'/api/files'}]){
  assert.equal(validateDemoExport(payload(patch),100),false,JSON.stringify(patch));
 }
});

test('portal ignores foreign origin/source and deduplicates valid exports without API access',async()=>{
 const win=browser(),acks=[],source={postMessage(...args){acks.push(args)}},frame={contentWindow:source};
 const receiver=connectDemoDownloads(win,{frame,origin:demoOrigin,maxBytes:100});
 const message={source,origin:demoOrigin,data:payload()};
 win.emit('message',{...message,source:{}});win.emit('message',{...message,origin:'https://evil.example'});
 win.emit('message',{...message,data:payload({buffer:new ArrayBuffer(0)})});
 assert.equal(win.downloads.length,0);
 win.emit('message',message);win.emit('message',message);await settle();
 assert.equal(win.downloads.length,1);assert.equal(win.downloads[0].name,'document.html');
 assert.equal(await win.downloads[0].blob.text(),'real document');
 assert.equal(win.downloads[0].blob.type,'application/octet-stream');
 assert.ok(acks.some(([ack,origin])=>ack.ok===true&&ack.id===message.data.id&&origin===demoOrigin));
 receiver.dispose();assert.equal(win.revoked.length,1);
 win.emit('message',{...message,data:payload({id:'demo-87654321'})});assert.equal(win.downloads.length,1);
});

test('portal rejects stale frame identity and keeps Blob URL retention bounded',async()=>{
 const win=browser(),source={postMessage(){}},frame={contentWindow:source};
 const receiver=connectDemoDownloads(win,{frame,origin:demoOrigin,maxBytes:100});
 for(let n=0;n<40;n++){win.emit('message',{source,origin:demoOrigin,data:payload({id:'demo-'+String(n).padStart(8,'0')})});await settle()}
 assert.equal(win.downloads.length,40);assert.ok(win.revoked.length>=38);
 frame.contentWindow={};win.emit('message',{source,origin:demoOrigin,data:payload()});assert.equal(win.downloads.length,40);
 receiver.dispose();assert.equal(win.revoked.length,40);
});

test('host forwards real bytes and accepts only matching parent acknowledgements',async()=>{
 const win=browser(),sent=[];win.parent={postMessage(...args){sent.push(args)}};
 const adapter=installDemoExports(win,{portalOrigin,maxBytes:100,timeoutMs:1000});
 const pending=adapter.exportBlob(new Blob(['important'],{type:'text/plain'}),'notes.txt');await settle();
 assert.equal(sent.length,1);const [message,origin,transfers]=sent[0];
 assert.equal(origin,portalOrigin);assert.equal(new TextDecoder().decode(message.buffer),'important');assert.equal(transfers[0],message.buffer);
 await assert.rejects(adapter.exportBlob(new Blob(['second']),'second.txt'),/current download/);
 let done=false;pending.then(()=>done=true);
 for(const event of [{source:{},origin:portalOrigin},{source:win.parent,origin:demoOrigin}])win.emit('message',{...event,data:{type:'liberty.demo.export-result',id:message.id,ok:true}});
 win.emit('message',{source:win.parent,origin:portalOrigin,data:{type:'liberty.demo.export-result',id:'demo-wrong-id',ok:true}});
 await settle();assert.equal(done,false);
 win.emit('message',{source:win.parent,origin:portalOrigin,data:{type:'liberty.demo.export-result',id:message.id,ok:true}});
 await pending;adapter.dispose();
});

test('host rejects empty/oversized export, timeout, negative ACK and disposed operations',async()=>{
 const win=browser(),sent=[];win.parent={postMessage(data){sent.push(data)}};
 const adapter=installDemoExports(win,{portalOrigin,maxBytes:10,timeoutMs:10});
 await assert.rejects(adapter.exportBlob(new Blob([]),'empty.txt'),/Invalid/);
 await assert.rejects(adapter.exportBlob(new Blob(['12345678901']),'big.txt'),/Invalid/);
 await assert.rejects(adapter.exportBlob(new Blob(['keep']),'keep.txt'),/did not confirm/);
 const rejected=adapter.exportBlob(new Blob(['keep']),'keep.txt');await settle();
 win.emit('message',{source:win.parent,origin:portalOrigin,data:{type:'liberty.demo.export-result',id:sent.at(-1).id,ok:false,error:'Download failed.'}});
 await assert.rejects(rejected,/Download failed/);
 const closed=adapter.exportBlob(new Blob(['keep']),'keep.txt');await settle();adapter.dispose();
 await assert.rejects(closed,/closed/);await assert.rejects(adapter.exportBlob(new Blob(['x']),'x.txt'),/closed/);
});

test('Blob anchors and save pickers forward once instead of downloading in the iframe',async()=>{
 const win=browser(),sent=[];win.parent={postMessage(data){sent.push(data);queueMicrotask(()=>win.emit('message',{source:win.parent,origin:portalOrigin,data:{type:'liberty.demo.export-result',id:data.id,ok:true}}))}};
 const click=win.HTMLAnchorElement.prototype.click,adapter=installDemoExports(win,{portalOrigin,maxBytes:100});
 const anchor=win.document.createElement('a');anchor.href=win.URL.createObjectURL(new Blob(['native']));anchor.download='native.bin';anchor.click();await settle();
 assert.equal(win.downloads.length,0);assert.equal(sent.length,1);assert.equal(new TextDecoder().decode(sent[0].buffer),'native');
 const writer=await (await win.showSaveFilePicker({suggestedName:'picker.txt'})).createWritable();await writer.write('picker bytes');await writer.close();
 assert.equal(sent.length,2);assert.equal(new TextDecoder().decode(sent[1].buffer),'picker bytes');assert.equal(win.downloads.length,0);
 adapter.dispose();assert.equal(win.HTMLAnchorElement.prototype.click,click);assert.equal(win.showSaveFilePicker,undefined);
});

test('Finish revokes every native Blob URL, including evicted and non-export URLs',()=>{
 const win=browser();win.parent={postMessage(){}};
 const adapter=installDemoExports(win,{portalOrigin,maxBytes:10});
 const urls=[win.URL.createObjectURL(new Blob(['12345678901'])),win.URL.createObjectURL({mediaSource:true})];
 for(let n=0;n<70;n++)urls.push(win.URL.createObjectURL(new Blob(['x'])));
 win.URL.revokeObjectURL(urls[0]);adapter.dispose();adapter.dispose();
 assert.deepEqual(new Set(win.revoked),new Set(urls));assert.equal(win.revoked.length,urls.length);
});

test('suspended portal rejects late exports but retains URLs until confirmed cleanup',()=>{
 const win=browser(),source={postMessage(){}},frame={contentWindow:source};
 const receiver=connectDemoDownloads(win,{frame,origin:demoOrigin});
 win.emit('message',{source,origin:demoOrigin,data:payload()});assert.equal(win.downloads.length,1);
 receiver.suspend();assert.equal(win.revoked.length,0);
 win.emit('message',{source,origin:demoOrigin,data:payload({id:'demo-87654321'})});assert.equal(win.downloads.length,1);
 receiver.dispose();assert.equal(win.revoked.length,1);
});
