import {startRecording} from './voice.js';
// A discussion is a topic opener: Billy's question is shown, the answer goes to main chat.
export function createDiscussion({api,esc,toast,showView,onState,sendAgent}) {
  const $=s=>document.querySelector(s);
  let context={},active=false,busy=false,recording=null,startingMic=false,config=null,generation=0,visible=false;
  const drafts=new Map();
  const key=c=>JSON.stringify(c);
  function motion(value){onState(active&&visible&&!document.hidden?value:null);}
  function controls(){
    $('#discuss-send').disabled=busy||!!recording||startingMic;
    $('#discuss-input').disabled=busy||!!recording||startingMic;
    $('#discuss-mic').disabled=busy||startingMic||!config?.voice_ready||!navigator.mediaDevices?.getUserMedia;
    $('#discuss-mic').textContent=recording?'Stop recording ■':'Talk to Billy ♩';
    $('#discuss-mic').setAttribute('aria-pressed',String(!!recording));
    $('#discuss-end').disabled=busy||startingMic;
  }
  function render(result){
    const messages=result.messages||[];
    $('#discuss-messages').innerHTML=messages.length?messages.map(m=>`<article class="discuss-message ${m.role}"><small>${m.role==='user'?'YOU':'BILLY'}</small><p>${esc(m.text)}</p></article>`).join(''):'<article class="discuss-message billy"><small>BILLY</small><p>Tell me what I should know about this topic, and I’ll pick it up in our chat.</p></article>';
    $('#discuss-scroll').scrollTop=$('#discuss-scroll').scrollHeight;
  }
  async function configure(){
    try{config=await api('/discussion/config');
      $('#discuss-voice-note').textContent=config.voice_ready?'Record → review transcript → send. Audio goes to Meta for transcription.':'Voice is not connected yet. You can discuss by text now.';
    }catch(e){$('#discuss-voice-note').textContent='Could not check the voice connection. Text is still available.';}controls();
  }
  function close(){active=false;onState(null);$('#discuss-session').hidden=true;$('#chat-scroll').hidden=false;$('#chat-form').hidden=false;}
  async function send(text){
    if(busy||recording||startingMic)return false;
    busy=true;controls();motion('thinking');
    try{const sent=await sendAgent(text,context);if(sent){close();showView('chats');}else motion('ready');return sent;}
    finally{busy=false;controls();}
  }
  async function open(next={},label='Discuss with Billy',question=''){
    if(busy||startingMic){toast('Finish this turn before switching discussions.');return;}
    await stopRecording(true);window.speechSynthesis?.cancel();
    drafts.set(key(context),$('#discuss-input').value);context=next;active=true;
    $('#discuss-input').value=drafts.get(key(context))||'';
    $('#discuss-context').textContent=label;$('#discuss-sidebar-context').textContent=label;$('#discuss-empty').hidden=true;$('#discuss-insights').hidden=false;$('#discuss-session').hidden=false;
    $('#chat-scroll').hidden=true;$('#chat-form').hidden=true;showView('chats');
    motion('ready');configure();
    const token=generation;busy=true;controls();$('#discuss-status').textContent='';
    try{const result=await api('/discussion',{...context,opening_question:question});if(token===generation)render(result);}
    catch(e){toast(e.message);$('#discuss-status').textContent='Could not open this topic. You can still write to Billy below.';render({messages:[]});}
    finally{busy=false;controls();$('#discuss-input').focus();}
  }
  async function stopRecording(discard=false){
    if(!recording)return;const captured=recording;recording=null;
    busy=true;controls();motion(discard?'ready':'transcribing');
    const token=generation;
    try{const blob=await captured.stop(discard);if(discard)return;
      $('#discuss-status').textContent='Transcribing…';const form=new FormData();form.append('file',blob,'speech.wav');
      const result=await api('/discussion/transcribe',form);if(token!==generation)return;
      $('#discuss-input').value=[$('#discuss-input').value,result.text].filter(Boolean).join(' ');drafts.set(key(context),$('#discuss-input').value);
      $('#discuss-status').textContent='Review the transcript, then Send to continue in chat.';$('#discuss-input').focus();
    }catch(e){toast(e.message);$('#discuss-status').textContent='Recording was not sent. Try again or type your answer.';}
    finally{busy=false;controls();motion('ready');}
  }
  $('#discuss-mic').onclick=async()=>{
    if(recording){await stopRecording();return;}if(busy||startingMic)return;
    window.speechSynthesis?.cancel();startingMic=true;controls();const token=generation;
    try{const capture=await startRecording(()=>stopRecording());if(token!==generation){await capture.stop(true);return;}recording=capture;motion('listening');$('#discuss-status').textContent='Listening… click Stop when you’re done (up to 60 seconds).';}
    catch(e){toast(e.message);motion('ready');}finally{startingMic=false;controls();}
  };
  $('#discuss-form').onsubmit=async e=>{e.preventDefault();const text=$('#discuss-input').value.trim();if(text&&await send(text)){$('#discuss-input').value='';drafts.delete(key(context));}};
  $('#discuss-input').oninput=()=>drafts.set(key(context),$('#discuss-input').value);
  $('#discuss-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('#discuss-form').requestSubmit();}};
  $('#discuss-end').onclick=async()=>{generation++;await stopRecording(true);window.speechSynthesis?.cancel();close();};
  $('#discuss-read-aloud').onchange=()=>{if(!$('#discuss-read-aloud').checked){window.speechSynthesis?.cancel();motion('ready');}};
  $('#discuss-return').onclick=()=>{showView('chats');if(active)$('#discuss-input').focus();else open(context,$('#discuss-context').textContent);};
  const pause=()=>{generation++;window.speechSynthesis?.cancel();stopRecording(true);onState(null);};
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
  window.addEventListener('pagehide',pause);
  return {open,view(name){visible=name==='chats';if(!visible)pause();else if(active)motion('ready');},configure};
}
