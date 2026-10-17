import test from 'node:test';
import assert from 'node:assert/strict';
import {canvasEntry} from '../liberty/static/canvas-density.mjs';

test('CSS-sized physical boxes at DPR 2 retain full editor resolution and native types',()=>{
  class Entry{} class Size{}
  const canvas={};
  const entry=Object.assign(new Entry(),{target:canvas,contentBoxSize:[{inlineSize:390,blockSize:665}],devicePixelContentBoxSize:[Object.assign(new Size(),{inlineSize:390,blockSize:665})]});
  const normalized=canvasEntry(entry,canvas,{devicePixelRatio:2});
  assert.equal(normalized,entry);
  assert.ok(normalized instanceof Entry);
  assert.ok(normalized.devicePixelContentBoxSize[0] instanceof Size);
  assert.equal(normalized.devicePixelContentBoxSize[0].inlineSize,780);
  assert.equal(normalized.devicePixelContentBoxSize[0].blockSize,1330);
});

test('correct native boxes, other elements and legacy fallback entries are untouched',()=>{
  const canvas={};
  for(const entry of [
    {target:canvas,contentBoxSize:[{inlineSize:390,blockSize:665}],devicePixelContentBoxSize:[{inlineSize:780,blockSize:1330}]},
    {target:{},contentBoxSize:[{inlineSize:390,blockSize:665}],devicePixelContentBoxSize:[{inlineSize:390,blockSize:665}]},
    {target:canvas,contentRect:{width:390,height:665}},
  ]){
    const original=entry.devicePixelContentBoxSize;
    assert.equal(canvasEntry(entry,canvas,{devicePixelRatio:2}),entry);
    assert.equal(entry.devicePixelContentBoxSize,original);
  }
});

test('fractional density uses pixel rounding and accepts native subpixel rounding',()=>{
  const canvas={};
  const entry={target:canvas,contentBoxSize:[{inlineSize:800,blockSize:600}],devicePixelContentBoxSize:[{inlineSize:800,blockSize:600}]};
  canvasEntry(entry,canvas,{devicePixelRatio:1.25});
  assert.equal(entry.devicePixelContentBoxSize[0].inlineSize,1000);
  assert.equal(entry.devicePixelContentBoxSize[0].blockSize,750);
  const original=entry.devicePixelContentBoxSize;
  canvasEntry(entry,canvas,{devicePixelRatio:1.25});
  assert.equal(entry.devicePixelContentBoxSize,original);
});
