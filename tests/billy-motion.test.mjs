import test from 'node:test';
import assert from 'node:assert/strict';
import {resolveBillyMotion,createBillyMotion} from '../site/app/billy-motion.js';
const ready={browser:{controller:'billy',busy:false,error:null,pending:null},document_jobs:0};
test('activity maps to idle, research and document motions',()=>{
  assert.equal(resolveBillyMotion(ready).motion,'idle');
  assert.equal(resolveBillyMotion({...ready,browser:{...ready.browser,busy:true,status:'Reading the page'}}).motion,'researching');
  assert.equal(resolveBillyMotion({...ready,document_jobs:1}).motion,'reading');
  assert.equal(resolveBillyMotion(ready,{documentRequests:1}).motion,'reading');
});
test('approvals and browser handoff take precedence over work',()=>{
  const busy={browser:{busy:true,controller:'you',pending:{id:'approval'}},document_jobs:2};
  assert.equal(resolveBillyMotion(busy).label,'Waiting for your decision');
  busy.browser.pending=null;
  assert.equal(resolveBillyMotion(busy).label,'You have the browser');
  assert.equal(resolveBillyMotion(busy).motion,'waiting');
});
test('errors and disconnection never display active research',()=>{
  assert.equal(resolveBillyMotion({...ready,browser:{...ready.browser,error:'HTTP 403'}}).motion,'waiting');
  const disconnected=resolveBillyMotion({browser:{busy:true,pending:{id:'stale'}},document_jobs:1},{connected:false});
  assert.equal(disconnected.motion,'idle');
  assert.equal(disconnected.tone,'offline');
  assert.equal(resolveBillyMotion(null).tone,'offline');
});

test('explicit pause survives activity, visibility and OS preference changes',()=>{
  const originals={document:globalThis.document,localStorage:globalThis.localStorage,matchMedia:globalThis.matchMedia};
  const listeners={};let preference=null,plays=0;
  const reduced={matches:false,addEventListener:(name,fn)=>listeners.motion=fn};
  const video={play:()=>{plays++;return Promise.resolve();},pause:()=>{},load:()=>{},setAttribute:()=>{},addEventListener:()=>{}};
  const button={setAttribute:()=>{}};
  const nodes={'#billy-video':video,'.billy-profile':{dataset:{}},'#billy-motion':button,'#billy-status':{},'#billy-state-label':{},'#status-dot':{}};
  try{
    globalThis.document={hidden:false,querySelector:s=>nodes[s],addEventListener:(name,fn)=>listeners[name]=fn};
    globalThis.localStorage={getItem:()=>preference,setItem:(_,value)=>{preference=value;}};
    globalThis.matchMedia=()=>reduced;
    const motion=createBillyMotion();motion.update(ready);
    assert.ok(plays>0);
    button.onclick();assert.equal(preference,'off');const before=plays;
    motion.update({...ready,document_jobs:1});
    reduced.matches=true;listeners.motion();reduced.matches=false;listeners.motion();
    document.hidden=true;listeners.visibilitychange();document.hidden=false;listeners.visibilitychange();
    assert.equal(plays,before);
    assert.equal(nodes['.billy-profile'].dataset.motion,'off');
  }finally{for(const [key,value] of Object.entries(originals)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}}
});
