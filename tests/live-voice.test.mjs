import test from 'node:test';
import assert from 'node:assert/strict';
import {floatToPcm16,pcm16ToFloat,bytesToBase64,base64ToBytes,socketURL,runFunctionCalls,billyHandlers} from '../site/app/live-voice.js';

test('audio conversion round-trips and clips out-of-range samples',()=>{
  const pcm=floatToPcm16(new Float32Array([0,0.5,-0.5,1.5,-1.5]));
  assert.deepEqual([...pcm],[0,16383,-16384,32767,-32768]);
  const back=pcm16ToFloat(new Uint8Array(pcm.buffer));
  assert.ok(Math.abs(back[1]-0.5)<0.001&&Math.abs(back[2]+0.5)<0.001);
  const bytes=new Uint8Array([1,2,3,250,251,252]);
  assert.deepEqual([...base64ToBytes(bytesToBase64(bytes))],[...bytes]);
});

test('socket url carries the token as the server-named query parameter',()=>{
  assert.equal(socketURL({url:'wss://example/ws',token_parameter:'access_token'},'auth_tokens/a b'),'wss://example/ws?access_token=auth_tokens%2Fa%20b');
});

test('function calls run in the browser and never throw into the session',async()=>{
  const responses=await runFunctionCalls([{id:'1',name:'ask_billy',args:{message:'hi'}},{id:'2',name:'delete_everything',args:{}},{id:'3',name:'boom'}],{
    ask_billy:async({message})=>({reply:'Got '+message}),
    boom:async()=>{throw new Error('failed');},
  });
  assert.deepEqual(responses,[{id:'1',name:'ask_billy',response:{reply:'Got hi'}},{id:'2',name:'delete_everything',response:{error:'Unknown function delete_everything'}},{id:'3',name:'boom',response:{error:'failed'}}]);
});

function fakeAgent(script){
  // script: array of snapshots returned by successive polls after send
  let snapshot=script.before,sent=[],polls=0;
  return {agent:{getSnapshot:()=>snapshot,send:async text=>{sent.push(text);snapshot=script.sending;return true;},poll:async()=>{snapshot=script.after[Math.min(polls++,script.after.length-1)];}},sent:()=>sent};
}

test('ask_billy waits for the reply that follows this request, not an older one',async()=>{
  const before={run:{status:'complete'},messages:[{id:1,role:'billy',text:'Old reply'}]};
  const {agent,sent}=fakeAgent({before,sending:{run:{status:'running'},messages:before.messages},after:[{run:{status:'running'},messages:before.messages},{run:{status:'waiting'},messages:[...before.messages,{id:3,role:'billy',text:'Two RFPs are ready.'}]}]});
  const h=billyHandlers({agentChat:agent,waitMs:5000,tick:1,sleep:async()=>{}});
  assert.deepEqual(await h.ask_billy({message:' Which are ready? '}),{status:'waiting',reply:'Two RFPs are ready.'});
  assert.deepEqual(sent(),['Which are ready?']);
});

test('ask_billy reports working when Billy takes longer than the wait, and refuses while busy',async()=>{
  const busy={run:{status:'running'},messages:[]};
  const {agent}=fakeAgent({before:{run:{status:'complete'},messages:[]},sending:busy,after:[busy]});
  const h=billyHandlers({agentChat:agent,waitMs:5,tick:1,sleep:async()=>{}});
  assert.equal((await h.ask_billy({message:'Draft it'})).status,'working');
  assert.equal((await h.ask_billy({message:'Again?'})).status,'working');
  assert.deepEqual(await h.ask_billy({message:'  '}),{error:'Nothing to ask.'});
});

test('billy_reply returns the latest reply and any run error',async()=>{
  const snap={run:{status:'error',error:'Budget reached.'},messages:[{id:9,role:'billy',text:'Last word.'}]};
  const {agent}=fakeAgent({before:snap,sending:snap,after:[snap]});
  assert.deepEqual(await billyHandlers({agentChat:agent}).billy_reply(),{status:'error',reply:'Last word.',error:'Budget reached.'});
});
