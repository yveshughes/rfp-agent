import test from 'node:test';
import assert from 'node:assert/strict';
import {resolveBillyMotion,createBillyMotion} from '../site/app/billy-motion.js';
const ready={browser:{controller:'billy',busy:false,error:null,pending:null},document_jobs:0};
test('activity wakes Billy from snoozing for research and documents',()=>{
  assert.equal(resolveBillyMotion(ready).motion,'snoozing');
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
  const nodes={'#billy-video':video,'#billy-phone':{hidden:true},'#billy-snooze':{hidden:true},'.billy-profile':{dataset:{}},'#billy-motion':button,'#billy-status':{},'#billy-state-label':{},'#status-dot':{}};
  try{
    globalThis.document={hidden:false,querySelector:s=>nodes[s],addEventListener:(name,fn)=>listeners[name]=fn};
    globalThis.localStorage={getItem:()=>preference,setItem:(_,value)=>{preference=value;}};
    globalThis.matchMedia=()=>reduced;
    const motion=createBillyMotion();motion.update({...ready,browser:{...ready.browser,busy:true}});
    assert.ok(plays>0);
    button.onclick();assert.equal(preference,'off');const before=plays;
    motion.update({...ready,document_jobs:1});
    reduced.matches=true;listeners.motion();reduced.matches=false;listeners.motion();
    document.hidden=true;listeners.visibilitychange();document.hidden=false;listeners.visibilitychange();
    assert.equal(plays,before);
    assert.equal(nodes['.billy-profile'].dataset.motion,'off');
    motion.update(ready);assert.equal(nodes['.billy-profile'].dataset.state,'snoozing');
    assert.equal(nodes['.billy-profile'].dataset.animate,'paused');
    assert.equal(nodes['#billy-snooze'].hidden,false);
    assert.equal(video.hidden,true);
    motion.update({...ready,browser:{...ready.browser,busy:true}});
    assert.equal(nodes['#billy-snooze'].hidden,true);
    assert.equal(video.hidden,false);
    assert.equal(plays,before);
  }finally{for(const [key,value] of Object.entries(originals)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}}
});

test('discussion wakes Billy and submission decisions still take priority',()=>{
  assert.equal(resolveBillyMotion(ready,{discussionState:'listening'}).motion,'voice');
  assert.equal(resolveBillyMotion(ready,{discussionState:'listening'}).label,'Listening to you…');
  assert.equal(resolveBillyMotion({...ready,browser:{pending:{id:'1'}}},{discussionState:'listening'}).motion,'waiting');
  assert.equal(resolveBillyMotion(ready,{discussionState:null}).motion,'snoozing');
});

 test('corded phone is limited to actual voice activity',()=>{
  for(const discussionState of ['listening','speaking','transcribing']) assert.equal(resolveBillyMotion(ready,{discussionState}).motion,'voice');
  for(const discussionState of ['ready','thinking']) assert.equal(resolveBillyMotion(ready,{discussionState}).motion,'discussing');
  assert.equal(resolveBillyMotion(ready,{discussionState:null}).motion,'snoozing');
});
