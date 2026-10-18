import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {brotliDecompressSync} from 'node:zlib';

test('the installed-representation fixture decompresses to the original bytes',()=>{
 const fixture=JSON.parse(readFileSync(new URL('./fixtures/encoded-asset.json',import.meta.url),'utf8'));
 assert.deepEqual(brotliDecompressSync(Buffer.from(fixture.br,'hex')),Buffer.from(fixture.plain,'hex'));
});
