import test from 'node:test';
import assert from 'node:assert/strict';
import {createWritable,saveTarget,serialSaver} from '../liberty/static/bridge.mjs';

test('save decisions preserve original and separate exports',()=>{
 const file={id:'id',name:'report.docx',etag:'"old"',parent:'folder',owned:true};
 assert.equal(saveTarget(file,'report.docx').method,'PUT');
 assert.equal(saveTarget(file,'report.pdf').method,'POST');
 assert.equal(saveTarget({...file,owned:false},'report.docx').method,'POST');
});
test('writable handles typed writes, seek, truncate and bounded output',async()=>{
 let saved;
 const writer=createWritable(async blob=>{saved=await blob.text()},16);
 await writer.write('abc');await writer.seek(1);await writer.write('Z');await writer.truncate(2);await writer.close();
 assert.equal(saved,'aZ');
 await assert.rejects(()=>writer.write('x'),/closed/);
 const limited=createWritable(async()=>{},3);
 await assert.rejects(()=>limited.write('1234'),/limit/);
});
test('failed cloud writes reject without claiming success',async()=>{
 const writer=createWritable(async()=>{throw Error('quota')},100);
 await writer.write('important');
 await assert.rejects(()=>writer.close(),/quota/);
});
test('serial exports await the previous save and recover after failure',async()=>{
 const states=[];const save=serialSaver(async n=>{states.push(n);if(n===1)throw Error('fail');return n});
 const a=save(1),b=save(2);await assert.rejects(()=>a);assert.equal(await b,2);assert.deepEqual(states,[1,2]);
});
test('writable accepts a Blob from an editor iframe realm',async()=>{
 let saved;
 const crossRealmBlob={size:3,type:'text/plain',arrayBuffer:async()=>new TextEncoder().encode('abc').buffer};
 const writer=createWritable(async b=>saved=await b.text(),100);
 await writer.write(crossRealmBlob);await writer.close();assert.equal(saved,'abc');
});
import {attachBridge} from '../liberty/static/bridge.mjs';
test('failed cloud save requests recovery in top-level document',async()=>{
 class Anchor{click(){}}
 class Input{click(){}}
 const win={URL:{createObjectURL:()=> 'blob:test',revokeObjectURL:()=>{}},HTMLAnchorElement:Anchor,HTMLInputElement:Input,
  document:{createElement:()=>new Anchor()},File,Event};
 const recovered=[];
 const bridge=attachBridge(win,{onExport:async()=>{throw Error('session expired')},onBackup:(blob,name)=>recovered.push([blob,name])});
 const handle=await win.showSaveFilePicker({suggestedName:'important.docx'}),writer=await handle.createWritable();
 await writer.write('unsaved data');await assert.rejects(()=>writer.close(),/session expired/);
 assert.equal(recovered.length,1);assert.equal(recovered[0][1],'important.docx');assert.equal(await recovered[0][0].text(),'unsaved data');
 bridge.dispose();
});
import {createDriveSaver} from '../liberty/static/bridge.mjs';
test('private copy of shared file and each export get subsequent revisions',async()=>{
 const source={id:'shared',name:'report.docx',owned:false,etag:'"shared"'};
 const calls=[];
 const save=createDriveSaver(()=>source,async target=>{calls.push(target);return {id:'copy',name:'report.docx',etag:'"'+calls.length+'"'}});
 await save(new Blob(['one']),'report.docx');await save(new Blob(['two']),'report.docx');
 assert.deepEqual(calls.map(c=>c.method),['POST','PUT']);assert.equal(calls[1].headers['If-Match'],'"1"');
});
test('local open uses a file input in a cross-origin iframe and respects types/multiple/cancel',async()=>{
 let selected=[new File(['one'],'one.txt'),new File(['two'],'two.txt')],input,nativeCalls=0;
 class Anchor{click(){}}
 class Input extends EventTarget{click(){input=this;queueMicrotask(()=>{this.files=selected;this.dispatchEvent(new Event(selected.length?'change':'cancel'))})}remove(){}}
 const win={URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},HTMLAnchorElement:Anchor,HTMLInputElement:Input,File,Event,DOMException,
  document:{createElement:tag=>tag==='input'?new Input():new Anchor(),body:{append(){}}},
  showOpenFilePicker:async()=>{nativeCalls++;throw new DOMException('Cross origin','SecurityError')}};
 const bridge=attachBridge(win,{onExport:async()=>{}});
 const handles=await win.showOpenFilePicker({multiple:true,types:[{accept:{'text/plain':['.txt']}}]});
 assert.equal(nativeCalls,0);assert.equal(input.multiple,true);assert.match(input.accept,/\.txt/);
 assert.deepEqual(await Promise.all(handles.map(async h=>(await h.getFile()).name)),['one.txt','two.txt']);
 selected=[];await assert.rejects(win.showOpenFilePicker(),{name:'AbortError'});bridge.dispose();
});
