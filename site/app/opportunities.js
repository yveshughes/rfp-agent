export function createOpportunityFeed({api,esc,toast,openRFP,showSources,showCompany,openDocument}) {
  const host=document.querySelector('#opportunity-feed');
  host.innerHTML=`
    <div class="opportunity-intro"><div><strong>Find your next opportunity.</strong><p class="muted">Explore RFPs and discover work that fits your business.</p></div><button id="refresh-opportunities">↻ Check sources</button></div>
    <div class="filters">
      <label class="search-box"><span>⌕</span><input id="opportunity-search" placeholder="Search opportunities or agencies" aria-label="Search all opportunities"></label>
      <select id="opportunity-fit" aria-label="Filter relevance"><option value="">All relevance</option><option value="strong">Strong relevance</option><option value="some">Some relevance</option><option value="low">Limited relevance</option><option value="pending">Not assessed</option></select>
      <select id="opportunity-availability" aria-label="Filter availability"><option value="active">Open &amp; unconfirmed</option><option value="">All availability</option><option value="open">Appears open</option><option value="unknown">To confirm</option><option value="closed">Closed</option></select>
    </div>
    <p id="opportunity-profile" class="opportunity-profile" hidden>Add your services to see which opportunities fit your business. <button id="opportunity-company">Complete company profile ↗</button></p>
    <p id="opportunity-count" class="muted" aria-live="polite"></p>
    <div class="table-wrap"><table><thead><tr><th><button data-feed-sort="title">Opportunity ↕</button></th><th><button data-feed-sort="agency">Agency ↕</button></th><th aria-sort="descending"><button data-feed-sort="fit">Relevance ↓</button></th><th><button data-feed-sort="deadline">Due ↕</button></th><th>Pipeline</th></tr></thead><tbody id="opportunity-rows"></tbody></table></div>
    <p class="muted opportunity-footnote">Confirm availability and requirements with the issuing agency before preparing a response.</p>`;
  const $=s=>host.querySelector(s);
  let data={rows:[],sources:[]},busy=false,sort='fit',ascending=false,signature='';
  const pretty=t=>{const d=new Date(t);return Number.isNaN(d.getTime())?'':d.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'});};
  const relevance=r=>r.fit.score===null?'Not assessed':r.fit.score>=65?'Strong relevance':r.fit.score>=30?'Some relevance':'Limited relevance';
  const availability=r=>r.imported?.status||'unknown';
  const fieldName=f=>({'company.overview':'Company overview','experience.services':'Services','experience.sectors':'Industries','experience.projects':'Past projects'})[f]||'Company profile';
  function details(r){
    if(!r.imported)return '';
    const item=r.imported;
    const hasDescription=['listing_excerpt','listing_description','detail_page_excerpt'].includes(item.description_quality)&&item.description;
    const checked=pretty(item.checked_at);
    return `<details class="opportunity-description"><summary>About this opportunity</summary><p>${esc(hasDescription?item.description:'A full description isn’t available yet. Visit the agency’s listing for the scope and requirements.')}</p>${checked?`<small>Last checked ${esc(checked)}</small>`:''}<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">View agency listing ↗</a></details>`;
  }
  function render(){
    const q=$('#opportunity-search').value.toLowerCase(),filter=$('#opportunity-fit').value,status=$('#opportunity-availability').value;
    const rows=data.rows.filter(r=>{
      const n=r.fit.score;
      return (!status||(status==='active'?availability(r)!=='closed':availability(r)===status))&&(!q||[r.title,r.agency,r.imported?.description||'',...r.fit.matches].join(' ').toLowerCase().includes(q))&&(!filter||(filter==='pending'?n===null:n!==null&&(filter==='strong'?n>=65:filter==='some'?n>=30&&n<65:n<30)));
    });
    rows.sort((a,b)=>{
      const av=sort==='fit'?a.fit.score:a[sort],bv=sort==='fit'?b.fit.score:b[sort];
      if(av===null||av===''||bv===null||bv==='')return av===bv?a.title.localeCompare(b.title):av===null||av===''?1:-1;
      const n=typeof av==='number'?av-bv:String(av).localeCompare(String(bv));return n?(ascending?n:-n):a.title.localeCompare(b.title);
    });
    $('#opportunity-count').textContent=`${q||filter||status?rows.length+' of ':''}${data.rows.length} opportunit${data.rows.length===1?'y':'ies'}${data.scanning?' · Checking for updates…':''}`;
    $('#opportunity-profile').hidden=!data.rows.some(r=>r.fit.label==='Needs company profile');
    $('#opportunity-rows').innerHTML=rows.map(r=>`
      <tr><td><button class="rfp-title-link" data-open="${r.id}">${esc(r.title)}</button>
        <small class="opportunity-status">${r.imported?esc({open:'Appears open',closed:'Closed',unknown:'Availability to confirm'}[availability(r)]):r.reviewed?(r.error?'Review incomplete':'Reviewed '+pretty(r.reviewed*1000)):'Awaiting review'}</small>${details(r)}</td>
        <td>${esc(r.agency)}</td>
        <td><details class="fit-explanation"><summary>${esc(relevance(r))}</summary>
          <p>${r.fit.score===null?(r.fit.label==='Needs company profile'?'Add your services to your company profile for a relevance assessment.':'More opportunity details are needed to assess relevance.'):'Based on shared terms in your company profile and the opportunity. This is an initial assessment, not a qualification check.'}</p>
          ${r.fit.matches.length?`<p>Related services and topics: ${esc(r.fit.matches.join(', '))}</p>`:''}
          ${r.fit.evidence.map(e=>`<p>${esc(fieldName(e.field))}${e.document_id?` · <button data-evidence="${esc(e.document_id)}" data-page="${e.page}">View supporting page ${e.page} ↗</button>`:''}</p>`).join('')}
          <a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">View agency listing ↗</a></details></td>
        <td>${esc(r.deadline||'To confirm')}</td>
        <td>${r.pursued?`<span class="badge">${esc(r.status)}</span>`:`<button class="opportunity-pursue" data-pursue="${r.id}">Pursue RFP</button>`}</td></tr>`).join('')||`<tr><td colspan="5">${data.rows.length?'No opportunities match your filters. Try another search.':'No opportunities yet. Choose sources for Billy to follow.'}</td></tr>`;
    host.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>openRFP(b.dataset.open,data.rows.find(r=>r.id===b.dataset.open)));
    host.querySelectorAll('[data-evidence]').forEach(b=>b.onclick=()=>openDocument(b.dataset.evidence,Number(b.dataset.page)));
    host.querySelectorAll('[data-pursue]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await api('/opportunities/'+b.dataset.pursue+'/pursue',{});signature='';await load();toast('Added to My RFPs.');}catch(e){toast(e.message);b.disabled=false;}});
    $('#refresh-opportunities').disabled=data.scanning;
    $('#refresh-opportunities').textContent=data.scanning?'Checking…':'↻ Check sources';
    host.querySelectorAll('[data-feed-sort]').forEach(b=>{const active=b.dataset.feedSort===sort;b.closest('th').setAttribute('aria-sort',active?(ascending?'ascending':'descending'):'none');b.textContent=({title:'Opportunity',agency:'Agency',fit:'Relevance',deadline:'Due'})[b.dataset.feedSort]+' '+(active?(ascending?'↑':'↓'):'↕');});
  }
  async function load(){if(busy)return;busy=true;try{const next=await api('/opportunities');const key=JSON.stringify(next);data=next;if(key!==signature){signature=key;render();}}catch(e){toast(e.message);}finally{busy=false;}}
  $('#opportunity-search').oninput=render;
  $('#opportunity-fit').onchange=render;
  $('#opportunity-availability').onchange=render;
  $('#opportunity-company').onclick=()=>showCompany();
  host.querySelectorAll('[data-feed-sort]').forEach(b=>b.onclick=()=>{if(sort===b.dataset.feedSort)ascending=!ascending;else{sort=b.dataset.feedSort;ascending=sort!=='fit';}render();});
  $('#refresh-opportunities').onclick=async()=>{if(!data.sources.length){showSources();return;}try{await api('/opportunities/refresh',{});await load();}catch(e){toast(e.message);}};
  return {load};
}
