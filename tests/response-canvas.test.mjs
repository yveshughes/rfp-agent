import test from 'node:test';
import assert from 'node:assert/strict';
import {canvasChanges,saveCanvasChanges} from '../site/app/response-canvas.js';
const sections=()=>['1','2','3'].map(id=>({id,title:`Section ${id}`,body:`Original ${id}`,checks:[{text:'Human review',done:false}],version:2}));
test('canvas saves only edited sections with original version and manual checks',async()=>{
  const saved=sections(),drafts=new Map(saved.map(s=>[`rfp:${s.id}`,structuredClone(s)])),calls=[];
  drafts.get('rfp:2').body='Revised response\n\nWith another paragraph.';
  const count=await saveCanvasChanges({id:'rfp',sections:saved,drafts,api:async(path,payload)=>{calls.push({path,payload});return {sections:[]};},onSaved:()=>{}});
  assert.equal(count,1);assert.equal(calls[0].path,'/rfps/rfp/sections/2');
  assert.equal(calls[0].payload.version,2);assert.deepEqual(calls[0].payload.checks,saved[1].checks);
  assert.equal(drafts.has('rfp:2'),false);assert.equal(drafts.get('rfp:1').body,'Original 1');
});
test('partial failure retains unsaved edits and retries without repeating a successful save',async()=>{
  let saved=sections();const drafts=new Map(saved.map(s=>[`rfp:${s.id}`,{...structuredClone(s),body:`Edited ${s.id}`}])) ,calls=[];
  await assert.rejects(saveCanvasChanges({id:'rfp',sections:saved,drafts,api:async(path,payload)=>{
    calls.push(path);if(path.endsWith('/2'))throw new Error('Newer version exists');
    return {sections:saved.map(s=>s.id==='1'?{...s,...payload,version:3}:s)};
  },onSaved:result=>{saved=result.sections;}}),/Newer version/);
  assert.equal(drafts.has('rfp:1'),false);assert.equal(drafts.get('rfp:2').body,'Edited 2');assert.equal(drafts.get('rfp:2').version,2);
  assert.equal(drafts.get('rfp:3').body,'Edited 3');
  assert.deepEqual(canvasChanges('rfp',saved,drafts).map(s=>s.id),['2','3']);
  assert.deepEqual(calls,['/rfps/rfp/sections/1','/rfps/rfp/sections/2']);
});
test('invalid draft is rejected before writing any section',async()=>{
  const saved=sections(),drafts=new Map(saved.map(s=>[`rfp:${s.id}`,{...s,body:'Changed'}]));drafts.get('rfp:3').title=' ';
  let called=false;
  await assert.rejects(saveCanvasChanges({id:'rfp',sections:saved,drafts,api:async()=>{called=true;},onSaved:()=>{}}),/section title/);
  assert.equal(called,false);
});

test('untouched section drafts adopt newer content while actual edits are retained',async()=>{
  const {syncCanvasDrafts}=await import('../site/app/response-canvas.js');
  const original=sections(),drafts=new Map(original.map(s=>[`rfp:${s.id}`,structuredClone(s)])),baselines=new Map(original.map(s=>[`rfp:${s.id}`,structuredClone(s)]));
  drafts.get('rfp:2').body='Local edit';
  const newer=original.map(s=>({...s,body:'New saved content',version:3}));
  syncCanvasDrafts('rfp',newer,drafts,baselines);
  assert.equal(drafts.has('rfp:1'),false);assert.equal(drafts.has('rfp:3'),false);
  assert.equal(drafts.get('rfp:2').body,'Local edit');assert.equal(drafts.get('rfp:2').version,2);
});
