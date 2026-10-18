import test from 'node:test';
import assert from 'node:assert/strict';
import {parseHTML} from 'linkedom';
import {graphicsAvailable,lightFormat,lightHTMLText,mountLightEditor} from '../liberty/static/light-editor.mjs';
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
test('inert HTML text extraction preserves block, list, table and explicit breaks',()=>{
 const {document}=parseHTML('<html><body></body></html>');
 assert.equal(lightHTMLText(document,'<p>One<br>Two</p><ul><li>Three</li><li>Four</li></ul><table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>'),'One\nTwo\nThree\nFour\nA\tB\nC\tD');
 assert.equal(lightHTMLText(document,'First<div>Second</div>'),'First\nSecond');
 assert.equal(lightHTMLText(document,'First<div><br></div><div>Third</div>'),'First\n\nThird');
 assert.equal(lightHTMLText(document,'Line<br>'),'Line\n');
 assert.equal(lightHTMLText(document,'&lt;b&gt;Literal&lt;/b&gt;'),'<b>Literal</b>');
});
test('HTML text extraction excludes executable, style, metadata and template contents',()=>{
 const {document}=parseHTML('<html><body></body></html>');
 assert.equal(lightHTMLText(document,'<head><title>Hidden</title><style>hidden style</style></head><p>Safe</p><script>hidden script</script><template>hidden template</template><iframe>hidden frame</iframe><a href="javascript:alert(1)">Link</a>'),'Safe\nLink');
 assert.equal(document.body.textContent,'');
});

test('demo light mode exposes local Open only through its admission callback before reading',async()=>{
 const {window}=parseHTML('<html><head></head><body></body></html>'),events=[];
 const editor=mountLightEditor(window,{demo:true,onState(){},onSave(){},admit:async()=>{
  events.push('admitted');return [{name:'local.html',size:60,text:async()=>{events.push('read');return '<p>Local text</p><img src="/not-fetched" onerror="alert(1)">'}}];
 }});
 const button=[...window.document.querySelectorAll('button')].find(button=>button.textContent==='Open TXT/HTML');
 assert.ok(button);button.dispatchEvent(new window.Event('click'));await new Promise(setImmediate);
 assert.deepEqual(events,['admitted','read']);assert.equal(window.document.querySelector('.light-document').textContent,'Local text');
 assert.equal(window.document.querySelector('.light-document img'),null);assert.equal(typeof editor.openFile,'function');
});

test('refused demo admission leaves the current document untouched',async()=>{
 const {window}=parseHTML('<html><head></head><body></body></html>');
 mountLightEditor(window,{demo:true,onState(){},onSave(){},admit:async()=>{throw Error('Budget exhausted')}});
 const before=window.document.querySelector('.light-document').textContent;
 const button=[...window.document.querySelectorAll('button')].find(button=>button.textContent==='Open TXT/HTML');
 assert.ok(button);button.dispatchEvent(new window.Event('click'));await new Promise(setImmediate);
 assert.equal(window.document.querySelector('.light-document').textContent,before);
 assert.match(window.document.querySelector('.light-status').textContent,/Budget exhausted/);
});
