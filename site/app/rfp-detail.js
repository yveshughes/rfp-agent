export function createRFPDetail({api,esc,toast,getDocuments,openDiscussion}) {
  const $=s=>document.querySelector(s);
  let id=null, tab='files', data=null, request=0, saving=false, savingNote=false;
  const drafts=new Map(), noteDrafts=new Map();
  const key=()=>`${id}:${tab}`;
  const part=()=>data?.sections.find(s=>s.id===tab);
  const draft=()=>{if(!drafts.has(key()))drafts.set(key(),structuredClone(part()));return drafts.get(key());};
  function renderTabs(){
    if(!data)return;
    const count=getDocuments().filter(d=>d.rfp_id===id).length;
    $('#rfp-work-tabs').innerHTML=`<button role="tab" aria-selected="${tab==='files'}" data-rfp-tab="files" aria-controls="rfp-work-panel">RFP Files <span>(${count})</span></button>`+data.sections.map(s=>`<button role="tab" aria-selected="${tab===s.id}" data-rfp-tab="${s.id}" aria-controls="rfp-work-panel">${esc(s.title)} <span>(${s.progress}%)</span></button>`).join('');
    document.querySelectorAll('[data-rfp-tab]').forEach(b=>b.onclick=()=>{if(saving)return;noteDrafts.set(key(),$('#rfp-discussion-input').value);tab=b.dataset.rfpTab;render();});
    $('#rfp-progress-label').textContent=`${data.progress}% reviewed`;
    $('#rfp-progress-bar').value=data.progress;
    $('#rfp-progress-detail').textContent=`${data.completed} of ${data.total} review checks`;
  }
  function render(){
    if(!data)return;
    renderTabs();
    $('#rfp-page-meta').textContent=[data.rfp.status,data.rfp.deadline?`Due ${data.rfp.deadline}`:''].filter(Boolean).join(' · ');
    const hasFiles=getDocuments().some(d=>d.rfp_id===id);
    const files=tab==='files', s=part();
    $('#rfp-files-panel').hidden=!files;$('#rfp-response-panel').hidden=files;
    $('#rfp-work-panel').setAttribute('aria-label',files?'RFP Files':s.title);
    $('#rfp-discussion').hidden=true;$('#rfp-discussion-input').value=noteDrafts.get(key())||'';
    const needs=s?.checks.filter(c=>!c.done)||[];
    $('#rfp-needs-title').textContent=files?(hasFiles?'Source documents':'Billy needs the source documents.'):needs.length?'Billy needs your input.':'This section’s checklist is complete.';
    $('#rfp-needs-copy').textContent=files?(hasFiles?'Review the saved originals and check for any missing attachments or addenda.':'Save the RFP, attachments, and addenda here so Billy can review the requirements.'):needs.length?needs.map(c=>c.text).join(' · '):'All checks are marked complete. You still review and approve the final response before submission.';
    renderNotes();
    if(files)return;
    const d=draft(), conflict=d.version!==s.version;
    $('#rfp-response-panel').innerHTML=`<form id="response-section-form"><div class="response-heading"><label>Section name<input id="response-section-title" value="${esc(d.title)}" maxlength="100" required></label><span class="badge">${s.progress}% saved</span></div><label class="response-label" for="response-body">Response draft</label><textarea id="response-body" rows="12" maxlength="50000" placeholder="Build this part of your response here…">${esc(d.body)}</textarea><div class="response-save-row"><button class="primary" id="save-response-section" ${conflict?'disabled':''}>Save section</button><span id="response-save-state" role="status">${conflict?'A newer version was saved elsewhere.':JSON.stringify(d)!==JSON.stringify(s)?'Unsaved changes':'All changes saved'}</span></div>${conflict?'<button type="button" id="response-load-saved">Load latest saved version and discard this draft</button>':''}<section class="response-checks"><h3>Completion checklist</h3><p class="muted">Mark what you’ve completed, then save. Progress tracks these checks; it does not verify compliance.</p><div id="response-check-items"></div><details><summary>Edit checklist</summary><p class="muted">Starter items are suggestions. Replace them with the actual RFP requirements, one per line.</p><textarea id="response-checklist-lines" rows="6" maxlength="20000">${esc(d.checks.map(c=>c.text).join('\n'))}</textarea><button type="button" id="apply-response-checklist">Apply checklist</button></details></section></form>`;
    const dirty=()=>{$('#response-save-state').textContent='Unsaved changes';};
    $('#response-section-title').oninput=e=>{d.title=e.target.value;dirty();};
    $('#response-body').oninput=e=>{d.body=e.target.value;dirty();};
    function checks(){
      $('#response-check-items').innerHTML=d.checks.map((c,i)=>`<label><input type="checkbox" data-response-check="${i}" ${c.done?'checked':''}><span>${esc(c.text)}</span></label>`).join('');
      document.querySelectorAll('[data-response-check]').forEach(b=>b.onchange=()=>{d.checks[Number(b.dataset.responseCheck)].done=b.checked;dirty();});
    }
    checks();
    if(saving)$('#response-section-form').querySelectorAll('input,textarea,button').forEach(el=>el.disabled=true);
    $('#apply-response-checklist').onclick=()=>{const lines=$('#response-checklist-lines').value.split('\n').map(v=>v.trim()).filter(Boolean);if(!lines.length||lines.length>40||lines.some(v=>v.length>500)){toast('Use 1–40 checklist items, up to 500 characters each.');return;}d.checks=lines.map(text=>({text,done:d.checks.find(c=>c.text===text)?.done||false}));checks();dirty();};
    if($('#response-load-saved'))$('#response-load-saved').onclick=()=>{drafts.delete(key());render();};
    $('#response-section-form').onsubmit=async e=>{
      e.preventDefault();if(saving||conflict)return;
      const target=id, targetTab=tab, targetKey=key();saving=true;const form=e.target;form.querySelectorAll('input,textarea,button').forEach(el=>el.disabled=true);
      try{const result=await api(`/rfps/${target}/sections/${targetTab}`,d);drafts.delete(targetKey);saving=false;if(id===target){data=result;render();}toast('Response section saved.');}
      catch(err){toast(err.message);if(id===target&&tab===targetTab){form.querySelectorAll('input,textarea,button').forEach(el=>el.disabled=false);$('#response-save-state').textContent='Not saved — your draft is retained.';}}
      finally{saving=false;if(id!==target&&tab!=='files')render();}
    };
  }
  function renderNotes(){
    if(!data)return;
    const notes=data.notes.filter(n=>n.section_id===tab);
    $('#rfp-discussion-notes').innerHTML=notes.map(n=>`<article class="rfp-note"><small>You · ${new Date(n.at*1000).toLocaleString()}</small><p>${esc(n.text)}</p>${tab!=='files'?`<button type="button" data-note-draft="${n.id}">Add to response draft ↗</button>`:''}</article>`).join('')||'<p class="muted">No discussion notes for this section yet.</p>';
    document.querySelectorAll('[data-note-draft]').forEach(b=>b.onclick=()=>{if(saving){toast('Wait for the section to finish saving.');return;}const n=notes.find(n=>String(n.id)===b.dataset.noteDraft), d=draft();d.body=[d.body,n.text].filter(Boolean).join('\n\n');$('#response-body').value=d.body;$('#response-save-state').textContent='Unsaved changes';toast('Added to your draft. Save the section to keep it.');});
  }
  $('#rfp-discuss-text').onclick=()=>openDiscussion({rfp_id:id,section:tab},`${data?.rfp.title||'RFP'} · ${part()?.title||'Files'}`);
  $('#rfp-show-notes').onclick=()=>{$('#rfp-discussion').hidden=!$('#rfp-discussion').hidden;if(!$('#rfp-discussion').hidden)$('#rfp-discussion-input').focus();};
  $('#rfp-discussion-input').oninput=e=>noteDrafts.set(key(),e.target.value);
  $('#rfp-discussion-form').onsubmit=async e=>{e.preventDefault();if(!id||!data||savingNote)return;const target=id,targetTab=tab,targetKey=key(),text=$('#rfp-discussion-input').value;if(!text.trim())return;savingNote=true;$('#rfp-note-send').disabled=true;$('#rfp-discussion-input').disabled=true;
    try{const result=await api(`/rfps/${target}/discussion/${targetTab}`,{text});noteDrafts.delete(targetKey);if(id===target){data.notes=result.notes;if(tab===targetTab){$('#rfp-discussion-input').value='';renderNotes();}}toast('Discussion note saved.');}catch(err){toast(err.message);}finally{savingNote=false;$('#rfp-note-send').disabled=false;$('#rfp-discussion-input').disabled=false;}
  };
  return {
    async open(rfp,selectedTab='files'){const token=++request;id=rfp.id||null;tab='files';data=null;
      $('#rfp-list-page').hidden=true;$('#rfp-detail-page').hidden=false;
      $('#rfp-page-title').textContent=rfp.title||'Add an RFP';$('#rfp-page-agency').textContent=rfp.agency||'YOUR RFP WORKSPACE';$('#rfp-page-meta').textContent=[rfp.status,rfp.deadline?`Due ${rfp.deadline}`:''].filter(Boolean).join(' · ');
      $('#rfp-metadata').open=!id;$('#rfp-work-tabs').hidden=!id;$('#rfp-work-panel').hidden=true;$('#rfp-overall-progress').hidden=!id;
      $('#rfp-work-tabs').innerHTML='<span class="muted">Loading response sections…</span>';
      if(!id)return;
      try{const result=await api(`/rfps/${id}/workspace`);if(token!==request)return;data=result;tab=data.sections.some(s=>s.id===selectedTab)?selectedTab:'files';$('#rfp-work-panel').hidden=false;render();}catch(err){if(token===request)$('#rfp-work-tabs').innerHTML='<span class="muted">Could not load sections. Reopen the RFP to retry.</span>';toast(err.message);}
    },
    back(){++request;$('#rfp-detail-page').hidden=true;$('#rfp-list-page').hidden=false;},
    filesChanged(){renderTabs();},
    async reloadNotes(){if(!id||!data)return;const target=id;try{const latest=await api(`/rfps/${id}/workspace`);if(id===target){data.notes=latest.notes;renderNotes();}}catch(e){toast(e.message);}},
  };
}
