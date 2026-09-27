import {renderChatAttachments} from './chat-attachments.js?v=pdf-thumbnail-1';
import {resolveAgentActivity} from './billy-motion.js?v=document-review-2';
import {renderChatOutcome} from './chat-cards.js?v=1';

export function createAgentChat({api,esc,toast,openRFP,openCompany,openDocument,onState,onSaved,importDocument,companyChatActive,resourceURL,onReply}) {
  const $=s=>document.querySelector(s);
  const host=document.createElement('div');host.id='agent-conversation';host.className='conversation';$('#chat-scroll').append(host);
  let snapshot=null,polling=false,sending=false,signature='',lastStatus='',discussionReply=false;
  function render(){
    const {run,messages,steps,config}=snapshot;
    $('#chat-status').textContent=config.configured?`Billy · ${config.provider} · ${run?.model||config.model}`:'Billy needs a Vultr inference connection before he can work.';
    onState(run?.status==='running'?'thinking':null,resolveAgentActivity(snapshot),snapshot);
    $('#chat-form button[type="submit"]').disabled=sending||$('#chat-form').dataset.uploading==='true'||run?.status==='running';
    const companyMode=companyChatActive();host.hidden=companyMode;
    if(companyMode){$('#conversation').hidden=false;return;}
    if(!run)return;
    $('#welcome').hidden=true;$('#conversation').hidden=true;
    const key=JSON.stringify([run,messages,steps,snapshot.pdfs]);if(signature===key)return;signature=key;
    const nearBottom=$('#chat-scroll').scrollHeight-$('#chat-scroll').scrollTop-$('#chat-scroll').clientHeight<140;
    host.innerHTML=messages.map(m=>{
      const outcome=renderChatOutcome(m.outcome,{esc,resourceURL});
      return `<div class="message${m.role==='user'?' user':''}">${m.role==='user'?'':'<span class="message-name">BILLY</span>'}${m.text?'':outcome.summary}<div style="white-space:pre-wrap">${esc(m.text)}</div>${outcome.actions}${renderChatAttachments(m.attachments,{esc,resourceURL})}</div>`;
    }).join('');
    host.querySelectorAll('[data-chat-rfp]').forEach(button=>button.onclick=()=>openRFP(button.dataset.chatRfp));
    host.querySelectorAll('[data-chat-document]').forEach(button=>button.onclick=()=>openDocument(button.dataset.chatDocument));
    host.querySelectorAll('.sent-attachment img').forEach(img=>img.onerror=()=>{img.hidden=true;});
    host.querySelectorAll('[data-chat-profile]').forEach(button=>button.onclick=()=>openCompany());
    host.querySelectorAll('.chat-rfp-cover img').forEach(img=>{img.onerror=()=>{img.hidden=true;img.nextElementSibling.hidden=false;};});
    const footer=document.createElement('div');footer.className='agent-job';
    const selectedCardShown=messages.some(m=>m.outcome?.rfps?.some(r=>r.id===run.rfp_id));
    footer.innerHTML=`<small>${esc(run.status==='running'?'Billy is working…':run.status==='waiting'?'Billy needs your input':run.status==='complete'?'Turn complete':'Work paused')}</small>${run.error?`<p>${esc(run.error)}</p><button id="agent-retry">Continue saved work ↗</button>`:''}${run.rfp_id&&!selectedCardShown?'<button id="agent-open-rfp">Open selected RFP ↗</button>':''}${run.status!=='running'?'<button id="agent-upload">Import previous response ↗</button>':''}`;
    host.append(footer);
    for(const pdf of (snapshot.pdfs||[]).filter(p=>p.rfp_id===run.rfp_id)){
      const card=document.createElement('a');card.className='agent-job';card.target='_blank';card.rel='noopener';
      card.href=resourceURL('/api/response-pdfs/'+encodeURIComponent(pdf.id));
      card.innerHTML=`<strong>▤ ${esc(pdf.name)}</strong><small>${pdf.pages} pages · ${pdf.stale?'Earlier version — sections have changed':'Saved review copy'} · Open PDF ↗</small>`;
      host.append(card);
    }
    if($('#agent-open-rfp'))$('#agent-open-rfp').onclick=()=>openRFP(run.rfp_id);
    if($('#agent-upload'))$('#agent-upload').onclick=importDocument;
    if($('#agent-retry'))$('#agent-retry').onclick=async()=>{try{snapshot=await api('/agent/resume',{});render();}catch(e){toast(e.message);}};
    if(nearBottom)$('#chat-scroll').scrollTop=$('#chat-scroll').scrollHeight;
    if(lastStatus==='running'&&run.status!=='running'){onSaved();if(discussionReply&&['complete','waiting'].includes(run.status))onReply?.(messages.filter(m=>m.role==='billy').at(-1)?.text);discussionReply=false;}lastStatus=run.status;
  }
  async function poll(){if(polling)return;polling=true;try{const previous=snapshot;snapshot=await api('/agent');try{snapshot.pdfs=await api('/response-pdfs');}catch{snapshot.pdfs=previous?.pdfs||[];}render();}catch{}finally{polling=false;}}
  async function send(text,context,document_ids=[]){
    if(sending||snapshot?.run?.status==='running'){toast('Billy is working. Wait for his next question.');return false;}
    sending=true;
    try{snapshot=await api('/agent/message',{text,context,document_ids,request_id:crypto.randomUUID()});discussionReply=!!context;render();return true;}
    catch(e){toast(e.message);return false;}finally{sending=false;if(snapshot)render();}
  }
  return {poll,send,getSnapshot:()=>snapshot,hasRun:()=>!!snapshot?.run};
}
