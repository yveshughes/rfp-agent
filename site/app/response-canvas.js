// The canvas edits the same versioned plain-text sections as the section tabs.
const sameContent=(a,b)=>a.title===b.title&&a.body===b.body&&JSON.stringify(a.checks)===JSON.stringify(b.checks);
export function syncCanvasDrafts(id,sections,drafts,baselines){
  for(const s of sections){const key=`${id}:${s.id}`,d=drafts.get(key),base=baselines.get(key);if(d&&base&&sameContent(d,base)){drafts.delete(key);baselines.delete(key);}}
}
export function canvasChanges(id,sections,drafts){
  return sections.filter(s=>{
    const d=drafts.get(`${id}:${s.id}`);
    return d&&(d.title!==s.title||d.body!==s.body||JSON.stringify(d.checks)!==JSON.stringify(s.checks));
  });
}
export async function saveCanvasChanges({id,sections,drafts,api,onSaved}){
  const changes=canvasChanges(id,sections,drafts);
  // Validate the whole local draft before starting any writes.
  for(const s of changes){
    const d=drafts.get(`${id}:${s.id}`);
    if(!d.title.trim()||d.title.length>100||d.body.length>50000)throw new Error('Use a section title up to 100 characters and a response up to 50,000 characters per section.');
  }
  for(const s of changes){
    const key=`${id}:${s.id}`,d=drafts.get(key);
    const saved=await api(`/rfps/${id}/sections/${s.id}`,{title:d.title,body:d.body,checks:d.checks,version:d.version});
    drafts.delete(key);onSaved(saved,s.id);
  }
  return changes.length;
}
export function createResponseCanvas({host,api,esc,toast,drafts,baselines,onSaved,onBusy}){
  let current=null,busy=false;
  const dirtyKeys=new Set();
  window.addEventListener('beforeunload',e=>{if([...dirtyKeys].some(key=>drafts.has(key))){e.preventDefault();e.returnValue='';}});
  function render(id,data){
    current={id,data};
    syncCanvasDrafts(id,data.sections,drafts,baselines);
    const changed=canvasChanges(id,data.sections,drafts);
    for(const s of data.sections){const key=`${id}:${s.id}`;if(changed.includes(s))dirtyKeys.add(key);else dirtyKeys.delete(key);}
    host.innerHTML=`<div class="canvas-toolbar"><div><strong>Response document</strong><span id="canvas-save-state" role="status">${changed.length?'Unsaved changes':'All changes saved'}</span></div><button id="save-response-document" class="primary" ${busy||!changed.length?'disabled':''}>Save response</button></div><p class="canvas-hint">Edit directly below. Save your changes before leaving. Edits require an updated review PDF before submission.</p><article class="response-paper" aria-label="Editable RFP response"><header><span>${esc(data.rfp.agency||'RFP RESPONSE')}</span><h2>${esc(data.rfp.title)}</h2></header>${data.sections.map(s=>{const d=drafts.get(`${id}:${s.id}`)||s,conflict=d.version!==s.version;return `<section class="canvas-section" data-canvas-section="${s.id}"><label class="sr-only" for="canvas-title-${s.id}">Section ${s.id} title</label><input class="canvas-section-title" id="canvas-title-${s.id}" value="${esc(d.title)}" maxlength="100" required><label class="sr-only" for="canvas-body-${s.id}">${esc(s.title)} response</label><textarea class="canvas-section-body" id="canvas-body-${s.id}" rows="1" maxlength="50000" placeholder="Write this part of your response…">${esc(d.body)}</textarea>${conflict?`<p class="canvas-conflict">A newer version of this section was saved elsewhere. Your edits are retained.</p><button type="button" data-canvas-reload="${s.id}" class="canvas-reload">Discard my edits to this section and load the saved version</button>`:''}</section>`;}).join('')}<footer>End of response · Review all placeholders, required forms and attachments before submitting.</footer></article>`;
    const resize=el=>{el.style.height='auto';el.style.height=`${el.scrollHeight+2}px`;};
    host.querySelectorAll('.canvas-section-body').forEach(el=>{resize(el);});
    host.querySelectorAll('[data-canvas-section]').forEach(section=>{
      const sid=section.dataset.canvasSection,key=`${id}:${sid}`,source=data.sections.find(s=>s.id===sid),d=drafts.get(key)||structuredClone(source);
      const dirty=()=>{if(!baselines.has(key))baselines.set(key,structuredClone(source));drafts.set(key,d);dirtyKeys.add(key);host.querySelector('#canvas-save-state').textContent='Unsaved changes';host.querySelector('#save-response-document').disabled=false;};
      section.querySelector('input').oninput=e=>{d.title=e.target.value;dirty();};
      section.querySelector('textarea').oninput=e=>{d.body=e.target.value;resize(e.target);dirty();};
    });
    host.querySelectorAll('[data-canvas-reload]').forEach(b=>b.onclick=()=>{drafts.delete(`${id}:${b.dataset.canvasReload}`);baselines.delete(`${id}:${b.dataset.canvasReload}`);dirtyKeys.delete(`${id}:${b.dataset.canvasReload}`);render(id,data);});
    if(busy)host.querySelectorAll('input,textarea,button').forEach(el=>el.disabled=true);
    host.querySelector('#save-response-document').onclick=async()=>{
      if(busy)return;busy=true;onBusy(true);
      host.querySelectorAll('input,textarea,button').forEach(el=>el.disabled=true);
      host.querySelector('#canvas-save-state').textContent='Saving…';
      let savedCount=0,latest=data,error='';
      try{
        await saveCanvasChanges({id,sections:data.sections,drafts,api,onSaved:(result,sid)=>{latest=result;savedCount++;baselines.delete(`${id}:${sid}`);dirtyKeys.delete(`${id}:${sid}`);onSaved(result,id);}});
      }catch(e){
        error=e.message;
        // Refresh versions after a conflict without replacing the user's edits.
        try{latest=await api(`/rfps/${id}/workspace`);onSaved(latest,id);}catch{}
      }finally{
        busy=false;onBusy(false);
        if(current?.id===id){render(id,latest);if(error)host.querySelector('#canvas-save-state').textContent=savedCount?'Some sections saved. Remaining edits are retained; resolve the error before saving again.':'Not saved — your edits are retained.';}else if(current){render(current.id,current.data);}
      }
      toast(error||'Response saved. Update the review PDF before submitting.');
    };
  }
  let width=0;const observer=new ResizeObserver(()=>{const next=host.clientWidth;if(next===width)return;width=next;host.querySelectorAll('.canvas-section-body').forEach(el=>{el.style.height='auto';el.style.height=`${el.scrollHeight+2}px`;});});observer.observe(host);
  return {render,leave(){current=null;}};
}
