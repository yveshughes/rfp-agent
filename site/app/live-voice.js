// Live voice: Gemini Live is Billy's ears and mouth. Every question about the company or
// Billy's work goes through ask_billy, which posts to this workspace's agent API, so GLM on
// Vultr stays the only agent. The Gemini key never reaches the browser; the server mints a
// single-use token whose locked setup carries Billy's instruction and functions.
export function floatToPcm16(samples){
  const out=new Int16Array(samples.length);
  for(let i=0;i<samples.length;i++){const s=Math.max(-1,Math.min(1,samples[i]));out[i]=s<0?s*32768:s*32767;}
  return out;
}
export function pcm16ToFloat(bytes){
  const view=new Int16Array(bytes.buffer,bytes.byteOffset,bytes.byteLength>>1);
  const out=new Float32Array(view.length);
  for(let i=0;i<view.length;i++)out[i]=view[i]/32768;
  return out;
}
export function bytesToBase64(bytes){
  let text='';
  for(let i=0;i<bytes.length;i+=0x8000)text+=String.fromCharCode.apply(null,bytes.subarray(i,i+0x8000));
  return btoa(text);
}
export function base64ToBytes(text){
  const binary=atob(text);const out=new Uint8Array(binary.length);
  for(let i=0;i<binary.length;i++)out[i]=binary.charCodeAt(i);
  return out;
}
export function socketURL(socket,token){return `${socket.url}?${socket.token_parameter}=${encodeURIComponent(token)}`;}

// Waveform bars: RMS level per slice of 8-bit time-domain audio, eased toward the previous frame.
export function barHeights(samples,bars,previous=[],smoothing=0.55){
  const out=new Array(bars).fill(0),slice=Math.max(1,Math.floor(samples.length/bars));
  for(let b=0;b<bars;b++){
    let sum=0;const start=b*slice,end=Math.min(samples.length,start+slice);
    for(let i=start;i<end;i++){const v=(samples[i]-128)/128;sum+=v*v;}
    const rms=end>start?Math.sqrt(sum/(end-start)):0;
    const level=Math.min(1,Math.sqrt(rms*2.5));   // speech sits mid-height instead of pegging the bars
    out[b]=previous[b]===undefined?level:previous[b]+(level-previous[b])*(1-smoothing);
  }
  return out;
}

// Function calls run in the browser. Unknown names and thrown errors become error responses;
// nothing is executed that the workspace API itself would refuse.
export async function runFunctionCalls(calls,handlers){
  return Promise.all((calls||[]).map(async call=>{
    const handler=handlers[call.name];let response;
    try{response=handler?await handler(call.args||{}):{error:`Unknown function ${call.name}`};}
    catch(error){response={error:String(error?.message||error)};}
    return {id:call.id,name:call.name,response};
  }));
}

export function billyHandlers({agentChat,getContext=()=>undefined,waitMs=12000,tick=800,sleep=ms=>new Promise(r=>setTimeout(r,ms))}){
  const lastReply=snapshot=>snapshot?.messages?.filter(m=>m.role==='billy').at(-1)||null;
  return {
    async ask_billy({message}){
      const text=String(message||'').trim();
      if(!text)return {error:'Nothing to ask.'};
      if(agentChat.getSnapshot()?.run?.status==='running')return {status:'working',reply:'I am still busy with an earlier request. Ask me again in a moment.'};
      const previous=lastReply(agentChat.getSnapshot())?.id||0;
      if(!await agentChat.send(text,getContext()))return {error:'The request could not be sent to the workspace.'};
      const deadline=Date.now()+waitMs;
      while(Date.now()<deadline){
        await sleep(tick);await agentChat.poll();
        const snapshot=agentChat.getSnapshot(),run=snapshot?.run;
        if(run&&run.status!=='running'){
          const reply=lastReply(snapshot);
          if(reply&&reply.id>previous)return {status:run.status,reply:reply.text};
          if(run.error)return {status:run.status,error:run.error};
        }
      }
      return {status:'working',reply:'I am working on it. Ask me what I found in a moment.'};
    },
    async billy_reply(){
      await agentChat.poll();
      const snapshot=agentChat.getSnapshot(),run=snapshot?.run,reply=lastReply(snapshot);
      return {status:run?.status||'idle',reply:reply?.text||'Nothing yet.',...(run?.error?{error:run.error}:{})};
    },
  };
}

export function createLiveVoice({api,toast,agentChat,onState,elements}){
  const {button,bar,status,transcript,hangup,overlay,wave,overlayStatus,overlayHangup}=elements;
  let context=undefined;
  const handlers=billyHandlers({agentChat,getContext:()=>context});
  let ws=null,mic=null,player=null,active=false,ready=false,speaking=0,pendingCalls=0,config=null,resumeHandle=null,frame=0,heights=[];
  const lines={you:'',billy:''};
  const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
  const stateName=()=>!active?'off':!ready?'connecting':speaking>0?'speaking':pendingCalls>0?'thinking':'listening';
  function render(){
    const state=stateName();
    bar.hidden=!active;overlay.hidden=!active;overlay.dataset.state=state;
    button.setAttribute('aria-pressed',String(active));
    button.title=active?'Hang up':config?.ready?'Talk to Billy':'Live voice is not connected on the server';
    const label=!active?'':state==='connecting'?'Connecting…':state==='speaking'?'Billy is talking… interrupt any time.':state==='thinking'?'Billy is checking his workspace…':'Listening.';
    status.textContent=label;overlayStatus.textContent=label;
    transcript.innerHTML=[lines.you?`<p class="you"><span>You</span>${escapeHTML(lines.you)}</p>`:'',lines.billy?`<p class="billy"><span>Billy</span>${escapeHTML(lines.billy)}</p>`:''].join('');
  }
  // The waveform in front follows real audio: the microphone while listening, Billy's playback while
  // he speaks, a slow pulse while he checks the workspace. Everything behind it keeps updating.
  function draw(){
    if(!active){frame=0;return;}
    const context2d=wave.getContext('2d'),ratio=window.devicePixelRatio||1,width=wave.clientWidth,height=wave.clientHeight;
    if(wave.width!==Math.round(width*ratio)||wave.height!==Math.round(height*ratio)){wave.width=Math.round(width*ratio);wave.height=Math.round(height*ratio);}
    context2d.setTransform(ratio,0,0,ratio,0,0);context2d.clearRect(0,0,width,height);
    const bars=40,state=stateName();
    let levels;
    const analyser=state==='speaking'?player?.analyser:state==='listening'?mic?.analyser:null;
    if(analyser){const data=new Uint8Array(analyser.fftSize);analyser.getByteTimeDomainData(data);levels=barHeights(data,bars,heights,reducedMotion.matches?0.9:0.55);}
    else{const t=performance.now()/1000,pulse=state==='thinking'?0.18+0.12*Math.sin(t*3):0.06;levels=barHeights(new Uint8Array(bars).fill(128),bars,heights,0.8).map((v,i)=>Math.max(v,pulse*(0.6+0.4*Math.sin(i/3+t*2))));}
    heights=levels;
    const gap=4,barWidth=(width-gap*(bars-1))/bars,color=getComputedStyle(overlay).getPropertyValue('--wave-color').trim()||'#2f6b47';
    context2d.fillStyle=color;
    levels.forEach((level,i)=>{const h=Math.max(3,level*height);const x=i*(barWidth+gap),y=(height-h)/2;context2d.beginPath();context2d.roundRect(x,y,barWidth,h,barWidth/2);context2d.fill();});
    frame=document.hidden?0:requestAnimationFrame(draw);
  }
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&active&&!frame)frame=requestAnimationFrame(draw);});
  const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function setState(){onState(!active?null:speaking>0?'speaking':pendingCalls>0?'thinking':'listening');render();if(active&&!frame)frame=requestAnimationFrame(draw);}
  async function configure(){
    try{config=await api('/voice/config');}catch{config={ready:false};}
    button.disabled=!config.ready||!navigator.mediaDevices?.getUserMedia||typeof WebSocket==='undefined';
    render();
  }
  function send(payload){if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify(payload));}
  async function startMic(){
    const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    const context=new AudioContext({sampleRate:16000});await context.resume();
    await context.audioWorklet.addModule('/app/voice-worklet.js');
    const source=context.createMediaStreamSource(stream),node=new AudioWorkletNode(context,'billy-recorder');
    const analyser=context.createAnalyser();analyser.fftSize=1024;source.connect(analyser);
    let chunks=[],length=0;
    node.port.onmessage=event=>{
      if(!ready)return;
      chunks.push(event.data);length+=event.data.length;
      if(length<context.sampleRate/10)return;   // ~100 ms per message
      const joined=new Float32Array(length);let at=0;for(const c of chunks){joined.set(c,at);at+=c.length;}
      chunks=[];length=0;
      const pcm=floatToPcm16(joined);
      send({realtimeInput:{audio:{data:bytesToBase64(new Uint8Array(pcm.buffer)),mimeType:`audio/pcm;rate=${context.sampleRate}`}}});
    };
    source.connect(node);node.connect(context.destination);   // the worklet emits silence; this keeps it processing
    mic={stream,context,source,node,analyser};
  }
  function createPlayer(){
    const context=new AudioContext({sampleRate:24000});let nextTime=0;const sources=new Set();
    const analyser=context.createAnalyser();analyser.fftSize=1024;analyser.connect(context.destination);
    return {
      analyser,
      context,
      play(bytes){
        const samples=pcm16ToFloat(bytes);if(!samples.length)return;
        if(context.state==='suspended')context.resume().catch(()=>{});
        const buffer=context.createBuffer(1,samples.length,24000);buffer.copyToChannel(samples,0);
        const node=context.createBufferSource();node.buffer=buffer;node.connect(analyser);
        const start=Math.max(context.currentTime+0.02,nextTime);node.start(start);nextTime=start+buffer.duration;
        sources.add(node);speaking++;setState();
        node.onended=()=>{if(sources.delete(node)){speaking=Math.max(0,speaking-1);setState();}};
      },
      interrupt(){for(const node of sources){try{node.stop();}catch{}}sources.clear();nextTime=0;speaking=0;setState();},
      async close(){this.interrupt();if(context.state!=='closed')await context.close();},
    };
  }
  async function handleMessage(message){
    if(message.setupComplete){ready=true;setState();return;}
    if(message.toolCall){
      pendingCalls++;setState();
      try{const responses=await runFunctionCalls(message.toolCall.functionCalls,handlers);send({toolResponse:{functionResponses:responses}});}
      finally{pendingCalls=Math.max(0,pendingCalls-1);setState();}
      return;
    }
    if(message.sessionResumptionUpdate?.resumable&&message.sessionResumptionUpdate.newHandle)resumeHandle=message.sessionResumptionUpdate.newHandle;
    if(message.goAway)status.textContent='This call is about to end. Hang up and call again to continue.';
    const content=message.serverContent;if(!content)return;
    if(content.interrupted)player?.interrupt();
    if(content.inputTranscription?.text){if(lines.turn!=='you'){lines.you='';lines.turn='you';}lines.you+=content.inputTranscription.text;render();}
    if(content.outputTranscription?.text){if(lines.turn!=='billy'){lines.billy='';lines.turn='billy';}lines.billy+=content.outputTranscription.text;render();}
    for(const part of content.modelTurn?.parts||[])if(part.inlineData?.data)player?.play(base64ToBytes(part.inlineData.data));
    if(content.turnComplete)lines.turn=null;
  }
  async function start(options={}){
    if(active)return;
    context=options.context;
    // Create playback inside the click's activation; a context created after an await can stay suspended.
    player=createPlayer();player.context.resume().catch(()=>{});
    let session;
    try{session=await api('/voice/token',{});}catch(error){toast(error.message);await player.close();player=null;return;}
    active=true;ready=false;lines.you=lines.billy='';lines.turn=null;setState();
    try{
      const setup=resumeHandle?{...session.setup,sessionResumption:{handle:resumeHandle}}:session.setup;
      ws=new WebSocket(socketURL(session.socket,session.token));
      ws.onopen=()=>ws.send(JSON.stringify({setup}));
      ws.onmessage=async event=>{const text=typeof event.data==='string'?event.data:await event.data.text();let message;try{message=JSON.parse(text);}catch{return;}handleMessage(message).catch(error=>toast(error.message));};
      ws.onerror=()=>{if(active)toast('The voice connection failed.');};
      ws.onclose=event=>{if(!active)return;const reason=event.code===1000?'':` (${event.reason||event.code})`;stop();toast('Call ended'+reason+'.');};
      await startMic();
    }catch(error){toast(error.name==='NotAllowedError'?'Microphone access was declined.':error.message);await stop();}
  }
  async function stop(){
    if(!active)return;active=false;ready=false;
    const socket=ws;ws=null;if(socket&&socket.readyState<=WebSocket.OPEN)try{socket.close(1000,'hang up');}catch{}
    if(mic){mic.stream.getTracks().forEach(t=>t.stop());try{mic.source.disconnect();mic.node.disconnect();}catch{}if(mic.context.state!=='closed')await mic.context.close();mic=null;}
    if(player){await player.close();player=null;}
    speaking=0;pendingCalls=0;context=undefined;heights=[];if(frame){cancelAnimationFrame(frame);frame=0;}setState();
  }
  button.onclick=()=>active?stop():start();
  hangup.onclick=()=>stop();
  overlayHangup.onclick=()=>stop();
  window.addEventListener('pagehide',()=>{stop();});
  configure();
  return {start,stop,configure,isActive:()=>active,isReady:()=>!!config?.ready&&!button.disabled,debug:()=>({state:stateName(),speaking,pendingCalls,player:player?.context.state,mic:mic?.context.state,frame:!!frame}),sendText:text=>send({clientContent:{turns:[{role:'user',parts:[{text}]}],turnComplete:true}})};
}
