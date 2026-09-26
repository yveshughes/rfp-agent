// Capture mono PCM for Meta's WAV endpoint. No audio leaves the browser until Stop.
export function encodeWav(samples, rate) {
  const buffer=new ArrayBuffer(44+samples.length*2),v=new DataView(buffer);
  const str=(at,s)=>[...s].forEach((c,i)=>v.setUint8(at+i,c.charCodeAt(0)));
  str(0,'RIFF');v.setUint32(4,36+samples.length*2,true);str(8,'WAVE');str(12,'fmt ');
  v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,rate,true);v.setUint32(28,rate*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);str(36,'data');v.setUint32(40,samples.length*2,true);
  samples.forEach((s,i)=>v.setInt16(44+i*2,Math.max(-1,Math.min(1,s))*(s<0?32768:32767),true));
  return new Blob([buffer],{type:'audio/wav'});
}
export async function startRecording(onLimit) {
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
  let context,source,recorder,timer,closed=false;
  const chunks=[];
  const cleanup=async()=>{clearTimeout(timer);stream.getTracks().forEach(t=>t.stop());source?.disconnect();recorder?.disconnect();if(context&&context.state!=='closed')await context.close();};
  try {
    context=new AudioContext();await context.resume();
    await context.audioWorklet.addModule('/app/voice-worklet.js');
    source=context.createMediaStreamSource(stream);recorder=new AudioWorkletNode(context,'billy-recorder');
    recorder.port.onmessage=e=>{if(!closed)chunks.push(e.data);};
    source.connect(recorder);recorder.connect(context.destination);
    timer=setTimeout(onLimit,60000);
    return {async stop(discard=false){if(closed)return;closed=true;const rate=context.sampleRate;await cleanup();if(discard)return;
      const length=chunks.reduce((n,c)=>n+c.length,0);if(length<rate*.2)throw Error('Record a little longer, or type your answer.');
      const joined=new Float32Array(length);let at=0;chunks.forEach(c=>{joined.set(c,at);at+=c.length;});
      const offline=new OfflineAudioContext(1,Math.ceil(length*24000/rate),24000),input=offline.createBuffer(1,length,rate);input.copyToChannel(joined,0);
      const node=offline.createBufferSource();node.buffer=input;node.connect(offline.destination);node.start();
      return encodeWav((await offline.startRendering()).getChannelData(0),24000);
    }};
  }catch(e){await cleanup();throw e;}
}
