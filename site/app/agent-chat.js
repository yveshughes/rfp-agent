export function createAgentChat({api,esc,toast,openRFP,onState,onSaved,importDocument,companyChatActive}) {
  const $=s=>document.querySelector(s);
  const host=document.createElement('div');host.id='agent-conversation';host.className='conversation';$('#chat-scroll').append(host);
  let snapshot=null,polling=false,sending=false,signature='',lastStatus='';
  function render(){
    const {run,messages,steps,config}=snapshot;
    $('#chat-form small').textContent=config.configured?`Billy · ${config.provider} · ${run?.model||config.model}`:'Billy needs a Vultr inference connection before he can work.';
    onState(run?.status==='running'?'thinking':null);
    $('#chat-form button[type="submit"]').disabled=sending||run?.status==='running';
    const companyMode=companyChatActive();host.hidden=companyMode;
    if(companyMode){$('#conversation').hidden=false;return;}
    if(!run)return;
    $('#welcome').hidden=true;$('#conversation').hidden=true;
    const key=JSON.stringify([run,messages,steps]);if(signature===key)return;signature=key;
    const nearBottom=$('#chat-scroll').scrollHeight-$('#chat-scroll').scrollTop-$('#chat-scroll').clientHeight<140;
    host.innerHTML=messages.map(m=>`<div class="message${m.role==='user'?' user':''}">${m.role==='user'?'':'<span class="message-name">BILLY</span>'}<div style="white-space:pre-wrap">${esc(m.text)}</div></div>`).join('');
    const footer=document.createElement('div');footer.className='agent-job';
    footer.innerHTML=`<small>${esc(run.status==='running'?'Billy is working…':run.status==='waiting'?'Billy needs your input':run.status==='complete'?'Turn complete':'Work paused')} · ${steps.length} saved steps</small>${run.error?`<p>${esc(run.error)}</p><button id="agent-retry">Continue saved work ↗</button>`:''}${run.rfp_id?'<button id="agent-open-rfp">Open selected RFP ↗</button>':''}${run.status!=='running'?'<button id="agent-upload">Import previous response ↗</button>':''}`;
    host.append(footer);
    if($('#agent-open-rfp'))$('#agent-open-rfp').onclick=()=>openRFP(run.rfp_id);
    if($('#agent-upload'))$('#agent-upload').onclick=importDocument;
    if($('#agent-retry'))$('#agent-retry').onclick=async()=>{try{snapshot=await api('/agent/resume',{});render();}catch(e){toast(e.message);}};
    if(nearBottom)$('#chat-scroll').scrollTop=$('#chat-scroll').scrollHeight;
    if(lastStatus==='running'&&run.status!=='running')onSaved();lastStatus=run.status;
  }
  async function poll(){if(polling)return;polling=true;try{snapshot=await api('/agent');render();}catch{}finally{polling=false;}}
  async function send(text){
    if(sending||snapshot?.run?.status==='running'){toast('Billy is working. Wait for his next question.');return false;}
    sending=true;
    try{snapshot=await api('/agent/message',{text,request_id:crypto.randomUUID()});render();return true;}
    catch(e){toast(e.message);return false;}finally{sending=false;if(snapshot)render();}
  }
  return {poll,send,hasRun:()=>!!snapshot?.run};
}
