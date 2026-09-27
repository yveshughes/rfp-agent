import test from 'node:test';
import assert from 'node:assert/strict';
import {resolveBillyMotion,createBillyMotion,resolveBillyPanel,resolveAgentActivity} from '../site/app/billy-motion.js';
const ready={browser:{controller:'billy',busy:false,error:null,pending:null},document_jobs:0};
test('Autopilot stays visibly working between tools and keeps Activity open',()=>{
  for(const agentActivity of [null,'reading','researching']){
    const options={autopilotRunning:true,agentActivity,chatOpen:false};
    assert.equal(resolveBillyMotion(ready,options).motion,'autopilot');
    assert.equal(resolveBillyPanel(ready,options),'work');
  }
  assert.equal(resolveBillyMotion(ready,{autopilotRunning:false}).motion,'snoozing');
  assert.equal(resolveBillyMotion(ready,{autopilotRunning:true,connected:false}).motion,'idle');
});
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
  const nodes={'#billy-video':video,'#billy-idle-desk':{hidden:true},'#billy-snooze':{hidden:true},'.billy-profile':{dataset:{}},'#billy-motion':button,'#billy-status':{},'#billy-state-label':{},'#status-dot':{}};
  try{
    globalThis.document={hidden:false,querySelector:s=>nodes[s],addEventListener:(name,fn)=>listeners[name]=fn};
    globalThis.localStorage={getItem:()=>preference,setItem:(_,value)=>{preference=value;}};
    globalThis.matchMedia=()=>reduced;
    const motion=createBillyMotion();
    motion.update(null,{connected:false});
    assert.equal(nodes['#billy-idle-desk'].hidden,false);
    assert.equal(video.hidden,true);
    assert.equal(button.hidden,true);
    assert.equal(plays,0);
    motion.update({...ready,browser:{...ready.browser,busy:true}});
    assert.equal(nodes['#billy-idle-desk'].hidden,true);
    assert.equal(button.hidden,false);
    assert.ok(plays>0);
    motion.update(ready,{autopilotRunning:true});
    assert.equal(video.playbackRate,1.8);
    assert.equal(video.src,'/assets/billy/researching.mp4');
    assert.equal(nodes['#billy-state-label'].textContent,'Autopilot');
    assert.equal(nodes['#billy-snooze'].hidden,true);
    motion.update(ready,{discussionState:'listening'});
    assert.equal(video.src,'/assets/billy/voice-conversation.mp4');
    assert.equal(video.hidden,false);
    assert.equal(video.playbackRate,1);
    button.onclick();assert.equal(preference,'off');const before=plays;
    motion.update(ready,{discussionState:'speaking'});assert.equal(plays,before);
    motion.update(ready,{autopilotRunning:true});assert.equal(plays,before);
    motion.update({...ready,document_jobs:1});
    assert.equal(video.playbackRate,1);
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


test('opening chat wakes Billy while real work and decisions retain priority',()=>{
  assert.equal(resolveBillyMotion(ready,{chatOpen:true}).motion,'discussing');
  assert.equal(resolveBillyMotion(ready,{chatOpen:false}).motion,'snoozing');
  assert.equal(resolveBillyMotion(ready,{chatOpen:true,discussionState:'listening'}).motion,'voice');
  assert.equal(resolveBillyMotion({...ready,browser:{pending:{id:'approval'}}},{chatOpen:true}).motion,'waiting');
  assert.equal(resolveBillyMotion({...ready,document_jobs:1},{chatOpen:true}).motion,'reading');
  assert.equal(resolveBillyMotion(ready,{chatOpen:true,connected:false}).tone,'offline');
});


test('chat follows Discussing, actual research overrides thinking, and completion returns to chat',()=>{
  const chat={chatOpen:true,discussionState:'thinking'};
  assert.equal(resolveBillyPanel(ready,chat),'discuss');
  const browsing={...ready,browser:{...ready.browser,busy:true}};
  assert.equal(resolveBillyPanel(browsing,chat),'work');
  assert.equal(resolveBillyMotion(browsing,chat).motion,'researching');
  assert.equal(resolveBillyPanel({...ready,document_jobs:1},chat),'work');
  assert.equal(resolveBillyMotion({...ready,document_jobs:1},chat).motion,'reading');
  assert.equal(resolveBillyPanel(ready,chat),'discuss');
  assert.equal(resolveBillyPanel(ready,{chatOpen:false}),null);
});

test('agent document review selects Activity only during the current running turn',()=>{
  const snapshot={run:{status:'running'},messages:[{role:'user',created:10}],steps:[{tool:'read_document',created:11}]};
  assert.equal(resolveAgentActivity(snapshot),'reading');
  assert.equal(resolveBillyPanel(ready,{chatOpen:true,discussionState:'thinking',agentActivity:resolveAgentActivity(snapshot)}),'work');
  snapshot.run.status='waiting';assert.equal(resolveAgentActivity(snapshot),null);
  snapshot.run.status='running';snapshot.messages.push({role:'user',created:12});assert.equal(resolveAgentActivity(snapshot),null);
  snapshot.steps.push({tool:'open_source',created:13});assert.equal(resolveAgentActivity(snapshot),'researching');
  snapshot.steps.push({tool:'save_section',created:14});assert.equal(resolveAgentActivity(snapshot),'researching');
});

test('approval and browser control remain accessible without stale disconnected activity',()=>{
  assert.equal(resolveBillyPanel({...ready,browser:{...ready.browser,pending:{id:'approval'}}},{chatOpen:true}),'decisions');
  assert.equal(resolveBillyPanel({...ready,browser:{...ready.browser,controller:'you'}},{chatOpen:true}),'work');
  assert.equal(resolveBillyPanel({...ready,document_jobs:1},{chatOpen:true,connected:false}),'work');
  assert.equal(resolveBillyPanel(null,{chatOpen:true,discussionState:'ready'}),'work');
});

test('attached document review stays on Activity through extraction until Billy replies',()=>{
  const snapshot={run:{status:'running'},messages:[{role:'user',created:20,attachments:[{id:'proposal'}]}],steps:[]};
  const panel=()=>resolveBillyPanel(ready,{chatOpen:true,discussionState:snapshot.run.status==='running'?'thinking':null,agentActivity:resolveAgentActivity(snapshot)});
  assert.equal(panel(),'work');
  for(const [i,tool] of ['documents','read_document','save_fact','company','save_fact'].entries()){
    snapshot.steps.push({tool,created:21+i});
    assert.equal(resolveAgentActivity(snapshot),'reading');assert.equal(panel(),'work');
  }
  for(const status of ['waiting','complete','error']){snapshot.run.status=status;assert.equal(resolveAgentActivity(snapshot),null);assert.equal(panel(),'discuss');}
  snapshot.run.status='running';snapshot.messages.push({role:'user',created:30,text:'Hello'});
  assert.equal(resolveAgentActivity(snapshot),null);assert.equal(panel(),'discuss');
});
