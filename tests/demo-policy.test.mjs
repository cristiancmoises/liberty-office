import test from 'node:test';
import assert from 'node:assert/strict';
import {createDemoBudget,demoPolicy,validateDemoPaste,DEMO_LIMITS} from '../liberty/static/demo-policy.mjs';

function file(name,content='text',size){
 const bytes=new TextEncoder().encode(content);let reads=0;
 return {name,size:size??bytes.length,get reads(){return reads},async arrayBuffer(){reads++;return bytes.slice().buffer}};
}
const textPolicy=()=>demoPolicy('wordcraft');
const readMarker=()=>Error('Synthetic byte-read marker');
function large(size){return {name:'large.txt',size,reads:0,arrayBuffer(){this.reads++;return Promise.reject(readMarker())}}}
const widePolicy=()=>({...textPolicy(),maxFileBytes:50_000_000,maxDecodedBytes:100_000_000});

test('global input ceiling is decimal50MB and rejected metadata is never read',async()=>{
 assert.deepEqual(DEMO_LIMITS,{maxFileBytes:50_000_000,maxProjectBytes:100_000_000,maxProjectFiles:10});
 for(const size of [49_999_999,50_000_000,50_000_001]){
  const budget=createDemoBudget(),selected=large(size);
  await assert.rejects(budget.admit([selected],widePolicy()),size>50_000_000?/50 MB/:/byte-read marker/);
  assert.equal(selected.reads,size>50_000_000?0:1);
  assert.equal(budget.usage.bytes,size>50_000_000?0:size);
 }
});

test('nine and ten files are admitted cumulatively; the eleventh is refused before reads',async()=>{
 const budget=createDemoBudget();
 for(let n=0;n<10;n++){
  const selected=file('note-'+n+'.txt');assert.deepEqual(await budget.admit([selected],textPolicy()),[selected]);
  assert.equal(budget.usage.files,n+1);
 }
 const last=file('eleventh.txt');await assert.rejects(budget.admit([last],textPolicy()),/10 files/);assert.equal(last.reads,0);
 budget.resetAfterClear();assert.deepEqual(budget.usage,{files:0,bytes:0});
 assert.deepEqual(await budget.admit([last],textPolicy()),[last]);
});

test('aggregate99,999,999/100,000,000/100,000,001-byte boundaries reserve before reading',async()=>{
 for(const total of [99_999_999,100_000_000,100_000_001]){
  const budget=createDemoBudget(),first=large(50_000_000),second=large(total-50_000_000);
  await assert.rejects(budget.admit([first],widePolicy()),/byte-read marker/);
  // For total+1, split the second selection into two legal individual files.
  const selected=second.size>50_000_000?[large(50_000_000),large(1)]:[second];
  await assert.rejects(budget.admit(selected,widePolicy()),total>100_000_000?/100 MB/:/byte-read marker/);
  assert.equal(selected.reduce((sum,item)=>sum+item.reads,0),total>100_000_000?0:1);
  assert.equal(budget.usage.bytes,total>100_000_000?50_000_000:total);
 }
});

test('concurrent selections cannot overcommit or reset outstanding reads',async()=>{
 const budget=createDemoBudget();let complete;
 const selected={name:'pending.txt',size:50_000_000,arrayBuffer:()=>new Promise(resolve=>{complete=resolve})};
 const first=budget.admit([selected],widePolicy());
 const second=large(50_000_000);await assert.rejects(budget.admit([second],widePolicy()),/byte-read marker/);
 const excess=file('excess.txt');await assert.rejects(budget.admit([excess],widePolicy()),/100 MB/);assert.equal(excess.reads,0);
 assert.throws(()=>budget.resetAfterClear(),/pending/i);
 complete(new Uint8Array([65]).buffer);await assert.rejects(first,/changed/i);
 assert.deepEqual(budget.usage,{files:2,bytes:100_000_000});budget.resetAfterClear();
});

test('strict light2MiB and native policy limits reject before reads',async()=>{
 const policy=demoPolicy('wordcraft',{light:true});
 const exact=file('limit.txt','a',2*1024*1024),excess=file('limit.txt','a',2*1024*1024+1);
 await assert.rejects(createDemoBudget().admit([exact],policy),/changed/i);assert.equal(exact.reads,1);
 await assert.rejects(createDemoBudget().admit([excess],policy),/2 MiB/);assert.equal(excess.reads,0);
 for(const selected of [file('archive.docx'),file('no-extension'),file('../notes.txt')]){
  await assert.rejects(createDemoBudget().admit([selected],policy));assert.equal(selected.reads,0);
 }
 for(const appId of ['pdfcraft','filmcraft','unknown']){
  const selected=file('unqualified.pdf');await assert.rejects(createDemoBudget().admit([selected],demoPolicy(appId)),/not yet qualified/i);
  assert.equal(selected.reads,0);
 }
});

test('binary disguised as CSV, malformed UTF8 and excessive text structure never reach a native parser',async()=>{
 for(const content of ['PK\x03\x04','a\x00b','one\n'.repeat(10_001)]){
  await assert.rejects(createDemoBudget().admit([file('notes.txt',content)],textPolicy()));
 }
 const malformed={name:'notes.txt',size:2,arrayBuffer:async()=>new Uint8Array([0xc0,0xaf]).buffer};
 await assert.rejects(createDemoBudget().admit([malformed],textPolicy()),/UTF-8/);
 const decoded=file('notes.txt','abc');
 await assert.rejects(createDemoBudget().admit([decoded],{...textPolicy(),maxDecodedBytes:4}),/decoded/i);
});

test('CSV and TSV validate quotes, rows, columns, cells and field lengths before admission',async()=>{
 const policy=demoPolicy('gridcraft');
 for(const [name,content] of [['cells.csv','Name,Value\r\n"Hello, world",42'],['cells.tsv','Name\tValue\nAlice\t42']]){
  const selected=file(name,content);assert.deepEqual(await createDemoBudget().admit([selected],policy),[selected]);
 }
 for(const content of ['"unfinished,field','"closed"junk,field','x'.repeat(4097),Array(102).fill('x').join(','),'a\n'.repeat(2001),Array(201).fill(Array(100).fill('x').join(',')).join('\n')]){
  await assert.rejects(createDemoBudget().admit([file('cells.csv',content)],policy));
 }
 for(const bytes of [new Uint8Array([80,75,3,4]),new Uint8Array([0xd0,0xcf,0x11,0xe0])]){
  await assert.rejects(createDemoBudget().admit([{name:'disguised.csv',size:bytes.length,arrayBuffer:async()=>bytes.buffer}],policy));
 }
});

test('empty text is safe and a too-large selection is rejected before reading metadata',async()=>{
 const empty=file('empty.txt','');assert.deepEqual(await createDemoBudget().admit([empty],textPolicy()),[empty]);
 const explosive=Object.defineProperty({},'size',{get(){throw Error('Metadata should not be read')}});
 await assert.rejects(createDemoBudget().admit(Array(11).fill(explosive),textPolicy()),/10 files/);
});

test('Deck plain outlines reject archive dispatch and cap slide-producing lines',async()=>{
 const policy=demoPolicy('deckcraft'),outline=file('slides.md','First slide\n  - A bullet\nSecond slide');
 assert.deepEqual(await createDemoBudget().admit([outline],policy),[outline]);
 for(const content of ['PKnot-a-presentation','Slide\n'.repeat(101)]){
  await assert.rejects(createDemoBudget().admit([file('slides.txt',content)],policy));
 }
});

test('light markup and native text have bounded structural expansion before parsers',async()=>{
 await assert.rejects(createDemoBudget().admit([file('many.html','<b>x</b>'.repeat(5001))],demoPolicy('wordcraft',{light:true})),/markup/i);
 await assert.rejects(createDemoBudget().admit([file('paragraph.txt','x'.repeat(100_001))],textPolicy()),/line/i);
});

test('native pasted text cannot bypass bounded import through SVG, HTML, RTF or data URIs',()=>{
 for(const appId of ['wordcraft','vectorcraft','figcraft','effectcraft']){
  for(const value of ['<svg><rect/></svg>','<p>Rich HTML</p>','{\\rtf1 document}','data:image/svg+xml;base64,AAAA']){
   assert.throws(()=>validateDemoPaste(value,demoPolicy(appId)),/clipboard/i);
  }
  assert.equal(validateDemoPaste('Plain pasted text',demoPolicy(appId)),'Plain pasted text');
 }
 assert.equal(validateDemoPaste('<svg>literal source</svg>',demoPolicy('wordcraft',{light:true})),'<svg>literal source</svg>');
 assert.throws(()=>validateDemoPaste('x'.repeat(500_001),demoPolicy('wordcraft')));
 assert.throws(()=>validateDemoPaste(Array(201).fill(Array(100).fill('x').join('\t')).join('\n'),demoPolicy('gridcraft')),/cell/i);
 const quoted='"'+'a\n'.repeat(2001)+'"';assert.equal(validateDemoPaste(quoted,demoPolicy('gridcraft')),quoted);
 assert.throws(()=>validateDemoPaste(Array(50).fill('x'.repeat(100)).join(','),demoPolicy('gridcraft')),/field/i);
});

test('unknown app ids cannot inherit a policy from Object.prototype',()=>{
 for(const appId of ['__proto__','constructor','toString']){
  const policy=demoPolicy(appId);assert.equal(policy.qualified,false);assert.deepEqual(policy.extensions,[]);assert(Object.isFrozen(policy));
 }
});
