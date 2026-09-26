import test from 'node:test';
import assert from 'node:assert/strict';
import {encodeWav} from '../site/app/voice.js';
test('microphone output is mono 24 kHz signed 16-bit WAV, with clipped samples',async()=>{
  const blob=encodeWav(new Float32Array([-2,-1,0,1,2]),24000);
  const bytes=await blob.arrayBuffer(),v=new DataView(bytes);
  assert.equal(blob.type,'audio/wav');assert.equal(v.getUint16(22,true),1);
  assert.equal(v.getUint32(24,true),24000);assert.equal(v.getUint16(34,true),16);
  assert.equal(v.getUint32(40,true),10);
  assert.deepEqual(Array.from({length:5},(_,i)=>v.getInt16(44+i*2,true)),[-32768,-32768,0,32767,32767]);
});
