// Company facts are captured in scoped conversations, with explicit evidence provenance.
export function createCompanyProfile({api,esc,toast,showView,addMessage,openDocument,getState}) {
  const $=s=>document.querySelector(s);
  let profile=null, section='company', field=null, busy=false, signature='', chatField=sessionStorage.getItem('billy-company-field');
  const labels={'Reported by you':'reported','Evidence linked':'evidence','Unknown':'unknown','Gap reported':'gap'};
  const getField=()=>profile?.sections.flatMap(s=>s.fields).find(f=>f.id===field);
  function render(){
    if(!profile)return;
    const count=Object.values(profile.facts).filter(f=>f.value).length;
    $('#profile-progress').textContent=`${count} details recorded`;
    $('#company-sections').innerHTML=profile.sections.map(s=>`<button role="tab" aria-selected="${s.id===section}" aria-controls="company-section-body" data-company-section="${s.id}">${esc(s.name)}<span>${s.fields.filter(f=>profile.facts[f.id]?.value).length}/${s.fields.length}</span></button>`).join('')+`<button role="tab" aria-selected="${section==='documents'}" aria-controls="company-documents" data-company-section="documents">Documents <span>↗</span></button>`;
    document.querySelectorAll('[data-company-section]').forEach(b=>b.onclick=()=>{section=b.dataset.companySection;render();});
    $('#company-documents').hidden=section!=='documents';$('#company-section-body').hidden=section==='documents';
    if(section!=='documents'){
      const s=profile.sections.find(s=>s.id===section);
      $('#company-section-body').innerHTML=`<div class="profile-section-heading"><span class="eyebrow">COMPANY KNOWLEDGE</span><h2>${esc(s.name)}</h2><p>${esc(s.description)}</p></div>${section==='insurance'?'<div class="profile-callout"><strong>Close the gap before you bid.</strong><p>Billy can ask what you have, collect evidence, and keep follow-ups in one place.</p><button id="insurance-example">Try the $5M insurance conversation ↗</button><small>Illustrative requirement · check the actual RFP for its terms.</small></div>':''}<div class="profile-fields">${s.fields.map(f=>{
        const v=profile.facts[f.id];
        return `<article class="profile-fact"><div class="profile-fact-heading"><h3>${esc(f.label)}</h3><span class="fact-status ${labels[v?.status]||''}">${esc(v?.status||'Not added')}</span></div><p class="fact-value ${v?.value?'':'empty'}">${esc(v?.value||'Billy hasn’t collected this detail yet.')}</p>${v?.document_id?`<button class="evidence-link" data-profile-document="${esc(v.document_id)}" data-profile-page="${v.page}">Original document · page ${v.page} ↗</button>`:''}<div class="fact-footer"><button data-discuss="${f.id}">${v?'Discuss / update':'Add with Billy'} ↗</button>${v?`<small>Updated ${new Date(v.updated*1000).toLocaleDateString()}</small>`:''}</div></article>`;
      }).join('')}</div>`;
      document.querySelectorAll('[data-discuss]').forEach(b=>b.onclick=()=>discuss(b.dataset.discuss));
      document.querySelectorAll('[data-profile-document]').forEach(b=>b.onclick=()=>openDocument(b.dataset.profileDocument,Number(b.dataset.profilePage)));
      if($('#insurance-example'))$('#insurance-example').onclick=()=>discuss('insurance.coverage','insurance_example');
    }
    renderTasks();
  }
  function renderTasks(){
    const tasks=profile.tasks.filter(t=>t.status==='Queued');
    $('#company-task-count').textContent=tasks.length?`${tasks.length} queued`:'';
    $('#company-tasks').innerHTML=tasks.map(t=>`<button class="company-task" data-company-task="${esc(t.id)}"><span>○</span><strong>${esc(t.title)}</strong><small>Queued · open to review</small></button>`).join('')||'<p class="muted">No company follow-ups queued.</p>';
    document.querySelectorAll('[data-company-task]').forEach(b=>b.onclick=()=>{const t=profile.tasks.find(t=>t.id===b.dataset.companyTask);discuss(t.field);});
  }
  async function load(){try{const p=await api('/company');const next=JSON.stringify(p);profile=p;if(chatField&&!profile.sections.some(s=>s.fields.some(f=>f.id===chatField)))chatField=null;syncChatContext();if(next!==signature){signature=next;render();if($('#profile-dialog').open)renderDiscussion();}}catch(e){toast(e.message);}}
  function renderDiscussion(){
    const f=getField();if(!f)return;
    $('#profile-dialog-title').textContent=f.label;
    $('#profile-discussion').innerHTML=profile.messages.filter(m=>m.field===field).map(m=>`<div class="message ${m.role==='user'?'user':''}">${m.role==='billy'?'<span class="message-name">BILLY</span>':''}<div>${esc(m.text)}</div></div>`).join('');
    $('#profile-discussion').scrollTop=$('#profile-discussion').scrollHeight;
    $('#profile-evidence-value').value=profile.facts[field]?.value||'';
    const docs=getState()?.documents||[];const selected=$('#profile-evidence-document').value;
    $('#profile-evidence-document').innerHTML='<option value="">Choose a saved PDF</option>'+docs.map(d=>`<option value="${esc(d.id)}">${esc(d.name)}</option>`).join('');$('#profile-evidence-document').value=selected;
    $('#profile-followups').innerHTML=profile.tasks.filter(t=>t.field===field&&t.status==='Queued').map(t=>`<div class="profile-followup"><strong>${esc(t.title)}</strong><span class="badge">Queued</span><p>Saved for follow-up; research and policy verification have not run.</p><button data-task-status="Done" data-task-id="${esc(t.id)}">Mark done</button><button data-task-status="Cancelled" data-task-id="${esc(t.id)}">Cancel task</button></div>`).join('');
    document.querySelectorAll('[data-task-status]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{profile=await api('/company/tasks/'+b.dataset.taskId,{status:b.dataset.taskStatus});render();renderDiscussion();}catch(e){toast(e.message);b.disabled=false;}});
  }
  async function send(text,action='answer'){
    if(busy)return false;busy=true;$('#profile-send').disabled=true;
    try{const result=await api('/company/chat',{field,text,action});profile=result.profile;render();renderDiscussion();
      // Mirror the exchange into the main conversation without losing the field context.
      const sentField=field;
      if(action==='answer'){addMessage(`${getField().label}: ${text}`,true);addMessage(result.reply,false,[{label:'Continue company conversation ↗',action:()=>discuss(sentField)}]);}
      return true;
    }catch(e){toast(e.message);return false;}finally{busy=false;$('#profile-send').disabled=false;}
  }
  async function discuss(id,action){
    if(busy)return;
    if(!profile)await load();if(!profile)return;
    field=id;section=id.split('.')[0];showView('company');render();renderDiscussion();
    $('#profile-dialog').showModal();$('#profile-answer').value='';
    if(action||!profile.messages.some(m=>m.field===field))await send('Review this detail',action||'ask');
    $('#profile-answer').focus();
  }
  function syncChatContext(){const label=profile?.sections.flatMap(s=>s.fields).find(f=>f.id===chatField)?.label;$('#company-chat-context').hidden=!label;$('#company-chat-label').textContent=label?'Company Profile · '+label:'';$('#chat-input').placeholder=label?'Reply to Billy about '+label.toLowerCase()+'…':'Find a source… try Berkeley, CA';$('#chat-form label').textContent=label?'Reply to Billy about '+label:'Search for an agency or city';$('#chat-form button').setAttribute('aria-label',label?'Send company profile answer':'Send source search');$('#chat-form small').textContent=label?'Your answers update this company detail.':'Search a city or agency. Billy opens sources you choose.';}
  $('#profile-continue-chat').onclick=()=>{chatField=field;sessionStorage.setItem('billy-company-field',field);syncChatContext();$('#profile-dialog').close();showView('chats');$('#company-chat-context').hidden=false;$('#company-chat-label').textContent='Company Profile · '+getField().label;$('#chat-input').placeholder='Reply to Billy about '+getField().label.toLowerCase()+'…';addMessage(profile.messages.filter(m=>m.field===field&&m.role==='billy').at(-1)?.text||'Tell me what to record.');$('#chat-input').focus();};
  $('#company-chat-exit').onclick=()=>{chatField=null;sessionStorage.removeItem('billy-company-field');syncChatContext();$('#company-chat-context').hidden=true;$('#chat-input').placeholder='Find a source… try Berkeley, CA';};
  $('#close-profile-dialog').onclick=()=>$('#profile-dialog').close();
  $('#profile-chat-form').onsubmit=async e=>{e.preventDefault();const text=$('#profile-answer').value.trim();if(!text||busy)return;if(await send(text))$('#profile-answer').value='';};
  document.querySelectorAll('[data-profile-answer]').forEach(b=>b.onclick=()=>send(b.dataset.profileAnswer));
  $('#profile-evidence-form').onsubmit=async e=>{e.preventDefault();const b=$('#profile-evidence-save');b.disabled=true;try{profile=await api('/company/evidence',{field,document_id:$('#profile-evidence-document').value,page:Number($('#profile-evidence-page').value),value:$('#profile-evidence-value').value});render();renderDiscussion();toast('Detail saved with its source page.');}catch(err){toast(err.message);}finally{b.disabled=false;}};
  $('#profile-add-document').onclick=()=>{$('#profile-dialog').close();section='documents';render();};
  return {load,render,discuss,hasChat:()=>!!chatField,async answer(text){if(busy){toast('Billy is saving your previous answer.');return false;}field=chatField;return await send(text);},documents(){section='documents';showView('company');render();}};
}
