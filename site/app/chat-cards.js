export function renderChatOutcome(outcome,{esc,resourceURL}) {
  if(!outcome)return {summary:'',actions:''};
  const summary=outcome.summary?`<p class="chat-outcome-summary">${esc(outcome.summary)}</p>`:'';
  const profile=outcome.profile_updated?'<button type="button" class="chat-profile-link" data-chat-profile>View updated company profile ↗</button>':'';
  const cards=(outcome.rfps||[]).map(rfp=>{
    const preview=rfp.preview_document_id?resourceURL('/api/documents/'+encodeURIComponent(rfp.preview_document_id)+'/preview'):null;
    const deadline=/^\d{4}-\d{2}-\d{2}$/.test(rfp.deadline||'')?new Date(rfp.deadline+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}):rfp.deadline;
    const fallback=`<span class="chat-rfp-placeholder" ${preview?'hidden':''}><span class="chat-rfp-paper-icon" aria-hidden="true">▤</span><span>${esc(rfp.agency||'RFP opportunity')}</span><small>Opportunity details</small></span>`;
    return `<button type="button" class="chat-rfp-card" data-chat-rfp="${esc(rfp.id)}" aria-label="Open RFP: ${esc(rfp.title)}"><span class="chat-rfp-cover">${preview?`<img src="${esc(preview)}" alt="First page of ${esc(rfp.title)}" loading="lazy">`:''}${fallback}</span><span class="chat-rfp-body"><span class="chat-rfp-kind">${rfp.selected?'Selected to pursue':'Suggested for you'}</span><strong>${esc(rfp.title)}</strong><span class="chat-rfp-agency">${esc(rfp.agency)}</span>${rfp.reason?`<span class="chat-rfp-reason">${esc(rfp.reason)}</span>`:''}<span class="chat-rfp-bottom"><span>${deadline?`Due ${esc(deadline)}`:'Deadline to confirm'}</span><span>View RFP ↗</span></span></span></button>`;
  }).join('');
  return {summary,actions:profile+(cards?`<div class="chat-rfp-cards">${cards}</div>`:'')};
}
