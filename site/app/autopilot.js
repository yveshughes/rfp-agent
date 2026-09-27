export function createAutopilot({api,esc,toast,resourceURL,onChange,storageKey}){
  const $=s=>document.querySelector(s);
  let lastRunHTML='',lastTargetHTML='';
  let snapshot=null,rfp=null,busy=false,loading=false,last=0,reviewId=null;
  const reviews=new Map();
  const dismissedKey=storageKey('autopilot-dismissed-summary');
  let dismissedSummary='';
  try{dismissedSummary=localStorage.getItem(dismissedKey)||'';}catch{}
  const summaryId=run=>`${run?.id}:${run?.updated}`;
  function dismissSummary(value){dismissedSummary=value;try{if(value)localStorage.setItem(dismissedKey,value);else localStorage.removeItem(dismissedKey);}catch{}render();}
  function render(){
    const run=snapshot?.run,working=run?.status==='running',automatic=!!run?.autopilot;
    const finished=automatic&&run?.continuous&&run?.status==='complete'&&!run?.rfp_id;
    const dismissed=finished&&dismissedSummary===summaryId(run);
    const status=working&&automatic?'Preparing your next response':automatic&&run?.status==='paused'?'Autopilot paused':automatic&&run?.continuous&&run?.status==='complete'&&!run?.rfp_id?'Autopilot finished':automatic&&run?.blocked_reason?'Needs attention':'Autopilot';
    const runHTML=`<div>${dismissed?'<strong>Autopilot</strong>':`<strong>${status}</strong><p>Finds and prepares suitable RFPs, one after another.</p><small>Prioritizes fit and deadlines. Follow each response in My RFPs, and pause anytime.</small>${automatic&&run?.continuous&&run.queue_items?.length?`<p>${run.queue_items.filter(i=>i.status==='ready').length} ready for review · ${run.queue_items.filter(i=>i.status==='blocked').length} need attention</p>`:''}${automatic&&run?.blocked_reason?`<p>${esc(run.blocked_reason)}</p>`:''}${automatic&&run?.continuous&&run.queue_items?.some(i=>i.status==='blocked')?`<details><summary>Responses needing attention</summary>${run.queue_items.filter(i=>i.status==='blocked').map(i=>`<p><strong>${esc(i.title)}</strong><br>${esc(i.reason)}</p>`).join('')}</details>`:''}`}</div><div class="autopilot-actions">${finished?`<button data-autopilot-summary>${dismissed?'View last summary':'Dismiss'}</button>`:''}${working?`<button data-autopilot-pause ${busy?'disabled':''}>Pause Billy</button>`:`<button class="primary" data-autopilot-start ${busy||!snapshot?.config?.configured?'disabled':''}>${automatic&&['paused','error','interrupted'].includes(run?.status)?'Continue Autopilot':'Start Autopilot'}</button>`}${run?.rfp_id&&reviews.get(run.rfp_id)?.ready?`<button data-response-review="${esc(run.rfp_id)}">Review and submit ↗</button>`:''}</div>`;
    if(lastRunHTML!==runHTML){$('#autopilot-run').innerHTML=runHTML;lastRunHTML=runHTML;}
    $('#rfp-autopilot-controls').hidden=!rfp;
    const targetHTML=rfp?`<button data-autopilot-target ${working||busy||!snapshot?.config?.configured?'disabled':''}>Prepare with Autopilot</button>${reviews.get(rfp.id)?.ready?`<button class="primary" data-response-review="${esc(rfp.id)}">Review and submit ↗</button>`:''}`:'';
    if(lastTargetHTML!==targetHTML){$('#rfp-autopilot-controls').innerHTML=targetHTML;lastTargetHTML=targetHTML;}
    document.querySelectorAll('[data-autopilot-summary]').forEach(b=>b.onclick=()=>dismissSummary(dismissed?'':summaryId(run)));
    document.querySelectorAll('[data-autopilot-start]').forEach(b=>b.onclick=()=>start());
    document.querySelectorAll('[data-autopilot-target]').forEach(b=>b.onclick=()=>start(rfp));
    document.querySelectorAll('[data-autopilot-pause]').forEach(b=>b.onclick=()=>pause());
    document.querySelectorAll('[data-response-review]').forEach(b=>b.onclick=()=>openReview(b.dataset.responseReview));
  }
  async function start(target=null){
    if(busy)return;busy=true;render();
    try{
      const resume=!target&&snapshot?.run?.autopilot&&['paused','error','interrupted'].includes(snapshot.run.status);
      snapshot=await api(resume?'/agent/resume':'/agent/message',resume?{continuous:true}:{request_id:crypto.randomUUID(),autopilot:true,continuous:!target,context:target?{rfp_id:target.id}:null,
        text:target?`Use Autopilot to prepare ${target.title} for my review. Reuse this company's saved information and documents, consider the deadline, and prepare the response and review PDF without asking permission at each step. Flag missing details for my final review; do not submit.`:'Keep finding and preparing suitable RFPs with Autopilot, one after another, until I pause or no suitable opportunities remain. Add each selected RFP to My RFPs as Researching as soon as you pick it up. Prioritize fit and enough time to respond. Reuse this company’s saved information and documents, prepare the response and review PDF without asking permission at each step, and leave each response ready for my final review before moving to the next RFP. Flag missing details; do not submit.'});
      toast(resume?'Autopilot resumed.':target?'Billy is preparing this response for your review.':'Autopilot started. Follow Billy’s progress in My RFPs.');await onChange();
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
