import test from 'node:test';import assert from 'node:assert/strict';
import {validHandshake,validateExport,canReconnectEditor,connectEditor} from '../liberty/static/editor-client.mjs';
const frame={};const config={origin:'https://edit.example.org',nonce:'nonce',source:frame};
test('an open editor reconnects only to a full session of its original account',()=>{
 assert.equal(canReconnectEditor('alice',{state:'full',user:{id:'alice'}}),true);
 for(const session of [null,{state:'mfa',user:{id:'alice'}},{state:'full',user:{id:'bob'}}])assert.equal(canReconnectEditor('alice',session),false);
});
test('handshake rejects wrong origin source and nonce',()=>{
 const good={source:frame,origin:config.origin,data:{type:'liberty.ready',nonce:'nonce',documentId:'document-one'}};
 assert.equal(validHandshake(good,config),true);
 for(const change of [{source:{}},{origin:'https://evil.example.org'},{data:{type:'liberty.ready',nonce:'other'}}])assert.equal(validHandshake({...good,...change},config),false);
});
test('a reloaded document gets a new port; stale save results never reach the new generation',async()=>{
 const channels=[],listeners=new Map();let finish;
 class Port{constructor(){this.messages=[];this.closed=false}start(){}close(){this.closed=true}postMessage(data){this.messages.push(data)}}
 class Channel{constructor(){this.port1=new Port();this.port2=new Port();channels.push(this)}}
 const env={MessageChannel:Channel,setTimeout:()=>1,clearTimeout(){},addEventListener:(type,fn)=>listeners.set(type,fn),removeEventListener:type=>listeners.delete(type)};
 const frame={ownerDocument:{defaultView:env},contentWindow:{postMessage(){}}};
 const bridge=connectEditor(frame,config,{onExport:()=>new Promise(resolve=>{finish=resolve})});
 const ready=documentId=>listeners.get('message')({source:frame.contentWindow,origin:config.origin,data:{type:'liberty.ready',nonce:'nonce',documentId}});
 ready('document-one');ready('document-one');assert.equal(channels.length,1);
 const saving=channels[0].port1.onmessage({data:{type:'export',id:'export-1',name:'a.txt',buffer:new ArrayBuffer(1)}});
 ready('document-two');assert.equal(channels.length,2);assert.equal(channels[0].port1.closed,true);
 finish();await saving;assert.deepEqual(channels[1].port1.messages,[{type:'language',language:'en'}]);
 bridge.setLanguage('pt-BR');assert.deepEqual(channels[1].port1.messages.at(-1),{type:'language',language:'pt-BR'});
 await bridge.offer(new Blob(['next']),'next.txt');assert.equal(channels[1].port1.messages.at(-1).type,'offer');bridge.dispose();
});
test('export protocol accepts only bounded binary payload and safe request id',()=>{
 const good={type:'export',id:'export-1',name:'report.docx',buffer:new ArrayBuffer(3)};
 assert.equal(validateExport(good,10),true);
 for(const patch of [{id:'../../admin'},{name:''},{buffer:new ArrayBuffer(11)},{url:'/api/admin/users'},{type:'admin'}])assert.equal(validateExport({...good,...patch},10),false);
});
