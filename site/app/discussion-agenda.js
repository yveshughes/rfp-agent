const topicDescriptions={
  company:'Tell me about your business',
  services:'Let’s highlight your experience',
  insurance:'Let’s review your coverage',
  registrations:'Which licenses do you hold?',
  certifications:'Any certifications to include?',
  team:'Who’s on your team?',
  pricing:'Let’s talk rates and terms',
  references:'Who can vouch for your work?',
};
export function renderAgenda(data,esc){
  if(!data)return '<p class="muted">Loading open questions…</p>';
  const items=data.items||[];
  const rows=items.map((item,i)=>`<button type="button" class="agenda-topic" data-agenda-topic="${i}"><span class="agenda-circle" aria-hidden="true"></span><span><strong>${esc(item.label)}</strong><small>${esc(item.status==='Not added'?(topicDescriptions[item.id]||'Let’s talk this through'):item.status)}</small></span><span class="agenda-arrow" aria-hidden="true">↗</span></button>`);
  return `<p class="agenda-intro">${items.length?'Pick a topic. We’ll take it one question at a time.':'Nothing waiting to discuss. New questions will appear as we review your work.'}</p><p class="agenda-count">${items.length} open ${items.length===1?'topic':'topics'}</p>${rows.slice(0,5).join('')}${rows.length>5?`<details class="agenda-more"><summary>${rows.length-5} more ${rows.length===6?'topic':'topics'}</summary>${rows.slice(5).join('')}</details>`:''}<p class="agenda-footnote">Based on your saved profile and RFP review.</p>`;
}
export function createDiscussionAgenda({api,esc,onSelect}){
  const host=document.querySelector('#discussion-agenda');let busy=false,last=0,signature='';
  return {async refresh(force=false){
    if(busy||(!force&&Date.now()-last<5000))return;busy=true;last=Date.now();
    try{
      const data=await api('/discussion/agenda'),key=JSON.stringify(data);if(key===signature)return;signature=key;
      const expanded=host.querySelector('details')?.open;host.innerHTML=renderAgenda(data,esc);if(expanded&&host.querySelector('details'))host.querySelector('details').open=true;
      host.querySelectorAll('[data-agenda-topic]').forEach(button=>button.onclick=()=>onSelect(data.items[Number(button.dataset.agendaTopic)]));
    }catch{if(!signature)host.innerHTML='<p class="muted">Reconnect to see your open questions.</p>';}
    finally{busy=false;}
  }};
}
