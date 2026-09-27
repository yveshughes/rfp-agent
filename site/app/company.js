import {updateProfileCompletion} from './workspaces.js?v=profile-colors-1';
// Company facts are edited directly or captured by the main agent, with explicit evidence provenance.
export function createCompanyProfile({api,esc,toast,showView,openDocument,getState,openDiscussion}) {
  const $=s=>document.querySelector(s);
  let profile=null, section='company', field=null, signature='';
  let editing=null, savingEdit=false;
  const drafts=new Map();
  const labels={'Reported by you':'reported','Evidence linked':'evidence','Unknown':'unknown','Gap reported':'gap'};
  const getField=()=>profile?.sections.flatMap(s=>s.fields).find(f=>f.id===field);
  function render(){
    if(!profile)return;
    updateProfileCompletion(profile);
    const count=Object.values(profile.facts).filter(f=>f.value).length;
    $('#profile-progress').textContent=`${count} ${count===1?'detail':'details'} recorded`;
    $('#company-sections').innerHTML=profile.sections.map(s=>`<button role="tab" aria-selected="${s.id===section}" aria-controls="company-section-body" data-company-section="${s.id}">${esc(s.name)}<span>${s.fields.filter(f=>profile.facts[f.id]?.value).length}/${s.fields.length}</span></button>`).join('')+`<button role="tab" aria-selected="${section==='documents'}" aria-controls="company-documents" data-company-section="documents">Documents <span>↗</span></button>`;
    document.querySelectorAll('[data-company-section]').forEach(b=>b.onclick=()=>{if(savingEdit)return;editing=null;section=b.dataset.companySection;render();});
    $('#company-documents').hidden=section!=='documents';$('#company-section-body').hidden=section==='documents';
    if(section!=='documents'){
      const s=profile.sections.find(s=>s.id===section);
      $('#company-section-body').innerHTML=`<div class="profile-section-heading"><span class="eyebrow">COMPANY KNOWLEDGE</span><h2>${esc(s.name)}</h2><p>${esc(s.description)}</p></div><div class="profile-fields">${s.fields.map(f=>{
        const v=profile.facts[f.id];
        const isEditing=editing===f.id;
        return `<article class="profile-fact${isEditing?' editing':''}" data-fact="${f.id}"><div class="profile-fact-heading"><h3><button class="fact-label" data-edit="${f.id}" aria-label="Edit ${esc(f.label)}">${esc(f.label)}</button></h3><span class="fact-status ${labels[v?.status]||''}">${esc(v?.status||'Not added')}</span></div>${isEditing?`<form class="inline-fact-form" data-inline-form="${f.id}"><label class="sr-only" for="inline-fact-value">${esc(f.label)}</label><textarea id="inline-fact-value" rows="4" maxlength="6000" placeholder="Add ${esc(f.label.toLowerCase())}…">${esc(drafts.get(f.id)??v?.value??'')}</textarea><div class="inline-fact-actions"><button class="primary" type="submit">Save</button><button type="button" data-cancel-edit>Cancel</button><small>⌘ / Ctrl + Enter to save · Esc to cancel</small></div>${v?.document_id?'<p class="muted">Changing this detail clears its evidence link. You can attach a new source with Billy.</p>':''}</form>`:`<button class="fact-value fact-edit-target ${v?.value?'':'empty'}" data-edit="${f.id}" title="Edit ${esc(f.label)}">${esc(v?.value||'Click to add '+f.label.toLowerCase()+'…')}</button>${drafts.has(f.id)?'<small class="inline-draft-note">Unsaved edit · click to continue</small>':''}`}${v?.document_id?`<button class="evidence-link" data-profile-document="${esc(v.document_id)}" data-profile-page="${v.page}">View supporting source ↗</button>`:''}${v?.source_url?`<a class="evidence-link" href="${esc(v.source_url)}" target="_blank" rel="noopener noreferrer" title="${esc(v.source_quote||'')}">Company website ↗</a>`:''}<div class="fact-footer"><button data-discuss="${f.id}">Discuss with Billy ↗</button><button data-evidence-review="${f.id}">Evidence &amp; follow-ups</button>${v?`<small>Updated ${new Date(v.updated*1000).toLocaleDateString()}</small>`:''}</div></article>`;
      }).join('')}</div>`;
      bindInlineEditing();
      document.querySelectorAll('[data-evidence-review]').forEach(b=>b.onclick=()=>review(b.dataset.evidenceReview));
      document.querySelectorAll('[data-discuss]').forEach(b=>b.onclick=()=>discuss(b.dataset.discuss));
      document.querySelectorAll('[data-profile-document]').forEach(b=>b.onclick=()=>openDocument(b.dataset.profileDocument,Number(b.dataset.profilePage)));
    }
    renderTasks();
  }
  function bindInlineEditing(){
    function startEdit(id){if(savingEdit)return;editing=id;render();$('#inline-fact-value').focus();}
    document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>startEdit(b.dataset.edit));
    document.querySelectorAll('[data-fact]').forEach(row=>row.onclick=e=>{if(!e.target.closest('button,a,form'))startEdit(row.dataset.fact);});
    const form=$('[data-inline-form]');if(!form)return;
    const id=form.dataset.inlineForm, input=$('#inline-fact-value');
    input.oninput=()=>drafts.set(id,input.value);
    const cancel=()=>{if(savingEdit)return;drafts.delete(id);editing=null;render();document.querySelector(`[data-edit="${id}"]`)?.focus();};
    $('[data-cancel-edit]').onclick=cancel;
    input.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();cancel();}else if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();form.requestSubmit();}};
    form.onsubmit=async e=>{e.preventDefault();if(savingEdit)return;savingEdit=true;const value=input.value;drafts.set(id,value);form.querySelectorAll('button,textarea').forEach(el=>el.disabled=true);
      try{profile=await api('/company/facts/'+encodeURIComponent(id),{value});drafts.delete(id);editing=null;render();toast('Company detail saved.');document.querySelector(`[data-edit="${id}"]`)?.focus();}
      catch(err){toast(err.message);form.querySelectorAll('button,textarea').forEach(el=>el.disabled=false);input.focus();}
      finally{savingEdit=false;}
    };
  }
  function renderTasks(){
    const tasks=profile.tasks.filter(t=>t.status==='Queued');
    $('#company-task-count').textContent=tasks.length?`${tasks.length} queued`:'';
    $('#company-tasks').innerHTML=tasks.map(t=>`<button class="company-task" data-company-task="${esc(t.id)}"><span>○</span><strong>${esc(t.title)}</strong><small>Queued · open to review</small></button>`).join('')||'<p class="muted">No company follow-ups queued.</p>';
    document.querySelectorAll('[data-company-task]').forEach(b=>b.onclick=()=>{const t=profile.tasks.find(t=>t.id===b.dataset.companyTask);review(t.field);});
  }
  async function load(){try{const p=await api('/company');const next=JSON.stringify(p);profile=p;if(next!==signature&&!editing&&!savingEdit){signature=next;render();if($('#profile-dialog').open)renderReview();}}catch(e){toast(e.message);}}
  function renderReview(){
    const f=getField();if(!f)return;
    $('#profile-dialog-title').textContent=f.label;
    const history=profile.messages.filter(m=>m.field===field);
    $('#profile-discussion').innerHTML=history.length?history.map(m=>`<div class="message ${m.role==='user'?'user':''}">${m.role==='billy'?'<span class="message-name">BILLY</span>':''}<div>${esc(m.text)}</div></div>`).join(''):'<p class="muted">No edits, evidence links or follow-ups recorded for this detail yet.</p>';
    $('#profile-discussion').scrollTop=$('#profile-discussion').scrollHeight;
    $('#profile-evidence-value').value=profile.facts[field]?.value||'';
    const docs=getState()?.documents||[];const selected=$('#profile-evidence-document').value;
    $('#profile-evidence-document').innerHTML='<option value="">Choose a saved document</option>'+docs.map(d=>`<option value="${esc(d.id)}">${esc(d.name)}</option>`).join('');$('#profile-evidence-document').value=selected;
    $('#profile-followups').innerHTML=profile.tasks.filter(t=>t.field===field&&t.status==='Queued').map(t=>`<div class="profile-followup"><strong>${esc(t.title)}</strong><span class="badge">Queued</span><p>Saved for follow-up; research and policy verification have not run.</p><button data-task-status="Done" data-task-id="${esc(t.id)}">Mark done</button><button data-task-status="Cancelled" data-task-id="${esc(t.id)}">Cancel task</button></div>`).join('');
    document.querySelectorAll('[data-task-status]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{profile=await api('/company/tasks/'+b.dataset.taskId,{status:b.dataset.taskStatus});render();renderReview();}catch(e){toast(e.message);b.disabled=false;}});
  }
  // A topic conversation happens in main chat; Billy keeps the field as its context.
  function discuss(id){
    const label=profile?.sections.flatMap(s=>s.fields).find(f=>f.id===id)?.label||id;
    return openDiscussion({field:id},`Company Profile · ${label}`);
  }
  async function review(id){
    if(savingEdit)return;
    editing=null;
    if(!profile)await load();if(!profile)return;
    field=id;section=id.split('.')[0];showView('company');render();renderReview();
    $('#profile-dialog').showModal();
  }
  $('#close-profile-dialog').onclick=()=>$('#profile-dialog').close();
  $('#profile-evidence-form').onsubmit=async e=>{e.preventDefault();const b=$('#profile-evidence-save');b.disabled=true;try{profile=await api('/company/evidence',{field,document_id:$('#profile-evidence-document').value,page:Number($('#profile-evidence-page').value),value:$('#profile-evidence-value').value});render();renderReview();toast('Detail saved with its supporting source.');}catch(err){toast(err.message);}finally{b.disabled=false;}};
  $('#profile-add-document').onclick=()=>{$('#profile-dialog').close();section='documents';render();};
  return {load,render,discuss,review,selectSection(id){if(id==='documents'||profile?.sections.some(s=>s.id===id)){section=id;render();}},documents(){section='documents';showView('company');render();}};
}
