export function createAutopilot({api,esc,toast,resourceURL,onChange}){
  const $=s=>document.querySelector(s);
  let lastRunHTML='',lastTargetHTML='';
  let snapshot=null,rfp=null,busy=false,loading=false,last=0,reviewId=null;
  const reviews=new Map();
  function render(){
    const run=snapshot?.run,working=run?.status==='running',automatic=!!run?.autopilot;
    const status=working&&automatic?'Preparing your next response':automatic&&run?.status==='paused'?'Autopilot paused':automatic&&run?.blocked_reason?'Needs attention':'Autopilot';
    const runHTML=`<div><strong>${status}</strong><p>One best-fit RFP, prepared for your review.</p><small>Prioritizes fit and time to respond. You make the final submission.</small>${automatic&&run?.blocked_reason?`<p>${esc(run.blocked_reason)}</p>`:''}</div><div class="autopilot-actions">${working?`<button data-autopilot-pause ${busy?'disabled':''}>Pause Billy</button>`:`<button class="primary" data-autopilot-start ${busy||!snapshot?.config?.configured?'disabled':''}>${automatic&&['paused','error','interrupted'].includes(run?.status)?'Continue Autopilot':'Start Autopilot'}</button>`}${run?.rfp_id&&reviews.get(run.rfp_id)?.ready?`<button data-response-review="${esc(run.rfp_id)}">Review and submit ↗</button>`:''}</div>`;
    if(lastRunHTML!==runHTML){$('#autopilot-run').innerHTML=runHTML;lastRunHTML=runHTML;}
    $('#rfp-autopilot-controls').hidden=!rfp;
    const targetHTML=rfp?`<button data-autopilot-target ${working||busy||!snapshot?.config?.configured?'disabled':''}>Prepare with Autopilot</button>${reviews.get(rfp.id)?.ready?`<button class="primary" data-response-review="${esc(rfp.id)}">Review and submit ↗</button>`:''}`:'';
    if(lastTargetHTML!==targetHTML){$('#rfp-autopilot-controls').innerHTML=targetHTML;lastTargetHTML=targetHTML;}
    document.querySelectorAll('[data-autopilot-start]').forEach(b=>b.onclick=()=>start());
    document.querySelectorAll('[data-autopilot-target]').forEach(b=>b.onclick=()=>start(rfp));
    document.querySelectorAll('[data-autopilot-pause]').forEach(b=>b.onclick=()=>pause());
    document.querySelectorAll('[data-response-review]').forEach(b=>b.onclick=()=>openReview(b.dataset.responseReview));
  }
  async function start(target=null){
    if(busy)return;busy=true;render();
    try{
      const resume=!target&&snapshot?.run?.autopilot&&['paused','error','interrupted'].includes(snapshot.run.status);
      snapshot=await api(resume?'/agent/resume':'/agent/message',resume?{}:{request_id:crypto.randomUUID(),autopilot:true,context:target?{rfp_id:target.id}:null,
        text:target?`Use Autopilot to prepare ${target.title} for my review. Reuse this company's saved information and documents, consider the deadline, and prepare the response and review PDF without asking permission at each step. Flag missing details for my final review; do not submit.`:'Use Autopilot to find one best-fit RFP with enough time to respond. Reuse this company’s saved information and documents, prepare the response and review PDF without asking permission at each step, and bring it to my final review. Flag missing details; do not submit.'});
      toast(resume?'Autopilot resumed.':'Autopilot started. Billy will bring the response back for your review.');await onChange();
    }catch(e){toast(e.message);}finally{busy=false;render();}
  }
  async function pause(){if(busy)return;busy=true;render();try{snapshot=await api('/agent/pause',{});await onChange();}catch(e){toast(e.message);}finally{busy=false;render();}}
  async function refresh(){
    if(loading||Date.now()-last<5000)return;loading=true;last=Date.now();
    try{for(const id of new Set([rfp?.id,snapshot?.run?.rfp_id].filter(Boolean)))reviews.set(id,await api(`/rfps/${id}/review`));render();}
    catch{}finally{loading=false;}
  }
  async function openReview(id){
    reviewId=id;const dialog=$('#response-review-dialog');dialog.showModal();$('#response-review-content').innerHTML='<p>Loading your review copy…</p>';
    try{
      const r=await api(`/rfps/${id}/review`);if(reviewId!==id)return;
      const unchecked=r.sections.flatMap(s=>s.checks.filter(c=>!c.done));
      $('#response-review-content').innerHTML=`<span class="eyebrow">YOUR FINAL REVIEW</span><h2>${esc(r.rfp.title)}</h2><p>${r.expired?'The saved deadline has passed. Check the agency for an extension before proceeding.':r.closed?'This RFP is closed or already responded to. The saved draft remains available.':r.ready?'Your draft is ready to review. Check the details below before submitting through the agency.':'The review copy needs to be prepared or refreshed before submission.'}</p><p><strong>Deadline:</strong> ${esc(r.rfp.deadline||'Not confirmed — check the agency source')}</p>${r.pdf?`<a class="primary review-pdf-link" href="${esc(resourceURL(r.pdf.url))}" target="_blank" rel="noopener">Open review PDF · ${r.pdf.pages} ${r.pdf.pages===1?'page':'pages'} ↗</a>`:''}<h3>Details to check</h3>${r.gaps.length?'<ul>'+r.gaps.map(g=>`<li><strong>${esc(g.text)}</strong><p>${esc(g.gap_question||'Confirm this detail against the original requirements.')}</p></li>`).join('')+'</ul>':'<p>No missing details were recorded in Billy’s analysis. Please check the original requirements and all draft placeholders.</p>'}<p>${unchecked.length} response checks still need your review.</p><details><summary>Read the response</summary>${r.sections.map(s=>`<h3>${esc(s.title)}</h3><p class="review-section-text">${esc(s.body||'Not drafted yet.')}</p>`).join('')}</details><label class="review-confirm"><input id="review-confirm" type="checkbox" ${r.ready?'':'disabled'}> I’ve reviewed the draft, unresolved details, deadline, and required attachments.</label>${r.source_url?`<a id="review-submit-link" class="primary" aria-disabled="true" tabindex="-1" href="${esc(r.source_url)}" target="_blank" rel="noopener">Open source and submission instructions ↗</a>`:'<p>Add the agency’s submission link to the RFP details to continue.</p>'}<p class="muted">Submission takes place on the agency’s website. Nothing has been sent by Billy.</p>`;
      const link=$('#review-submit-link');if(link){link.onclick=e=>{if(!$('#review-confirm').checked)e.preventDefault();};$('#review-confirm').onchange=e=>{link.setAttribute('aria-disabled',String(!e.target.checked));link.tabIndex=e.target.checked?0:-1;};}
    }catch(e){$('#response-review-content').innerHTML=`<p>${esc(e.message)}</p>`;}
  }
  $('#response-review-close').onclick=()=>{$('#response-review-dialog').close();reviewId=null;};
  return {update(next){snapshot=next;render();refresh();},setRFP(next){rfp=next?.id?next:null;last=0;render();refresh();},openReview};
}
