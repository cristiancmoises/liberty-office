import test from 'node:test';
import assert from 'node:assert/strict';
import {graphicsAvailable,lightFormat} from '../liberty/static/light-editor.mjs';
test('unsupported graphics choose the lightweight editor without changing browser settings',async()=>{
 assert.equal(await graphicsAvailable({navigator:{},document:{createElement:()=>({getContext:()=>null})}}),false);
 let released=false;
 assert.equal(await graphicsAvailable({navigator:{},document:{createElement:()=>({getContext:()=>({getExtension:()=>({loseContext(){released=true}})})})}}),true);
 assert.equal(released,true);
});
test('an exposed WebGPU API with no usable adapter still falls back',async()=>{
 const win={navigator:{gpu:{requestAdapter:async()=>null}},document:{createElement:()=>({getContext:()=>null})}};
 assert.equal(await graphicsAvailable(win),false);
 win.navigator.gpu.requestAdapter=async()=>({});assert.equal(await graphicsAvailable(win),true);
});
test('light mode supports text and HTML, never silently rewrites Office documents',()=>{
 for(const name of ['notes.txt','NOTES.MD'])assert.equal(lightFormat(name),'text');
 assert.equal(lightFormat('notes.html'),'html');
 for(const name of ['letter.docx','table.xlsx','archive.zip','no-extension'])assert.throws(()=>lightFormat(name),/TXT/);
});
