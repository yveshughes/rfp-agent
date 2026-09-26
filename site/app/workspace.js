const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const local = ['localhost','127.0.0.1'].includes(location.hostname);
const API = local && location.port === '8080' ? 'http://127.0.0.1:8081' : '';
let state = null, offset = 0, sourceTotal = 0, currentView = 'chats', lastEvent = 0, initialized = false, frameURL = null, pendingFrame = false, searchTimer, pendingSearch = 0;
const views = {chats:'Chats',rfps:'RFPs',company:'Company Profile',artifacts:'Artifacts',settings:'Settings'};
const when = timestamp => new Date(timestamp * 1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});
const date = timestamp => new Date(timestamp * 1000).toLocaleDateString([], {month:'short',day:'numeric'});
function toast(message) { $('#toast').textContent=message; $('#toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('#toast').hidden=true,6500); }
async function api(path, data) {
  const opts = data === undefined ? {} : {method:'POST',headers:{'X-Billy-Client':'workspace'}};
  if(data instanceof FormData) opts.body=data;
  else if(data!==undefined){opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(data);}
  const response=await fetch(API+'/api'+path,opts);
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(typeof detail==='string'?detail:`Workspace request failed (${response.status}).`);}
  return response.json();
}
function showView(name) {
  currentView=name;
  Object.keys(views).forEach(view=>{ $('#view-'+view).hidden=view!==name; document.querySelector(`[data-view="${view}"]`).classList.toggle('selected',view===name); });
  $('#view-title').textContent=views[name];
  if(name==='rfps') loadSources();
  if(name==='company') renderDocuments();
  if(name==='artifacts') renderArtifacts();
}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>showView(button.dataset.view)));
$('#collapse-nav').onclick=()=>{const collapsed=$('#workspace').classList.toggle('nav-collapsed');$('#collapse-nav').setAttribute('aria-label',collapsed?'Expand navigation':'Collapse navigation');};
function selectPanel(name){document.querySelectorAll('[data-panel]').forEach(x=>x.setAttribute('aria-selected',String(x.dataset.panel===name)));$('#panel-work').hidden=name!=='work';$('#panel-decisions').hidden=name!=='decisions';}
document.querySelectorAll('[data-panel]').forEach(button=>button.onclick=()=>selectPanel(button.dataset.panel));
function addMessage(text, user=false, buttons=[]) {
  $('#welcome').hidden=true;
  const div=document.createElement('div');div.className='message'+(user?' user':'');
  if(!user){const label=document.createElement('span');label.className='message-name';label.textContent='BILLY';div.append(label);}
  const content=document.createElement('div');content.textContent=text;div.append(content);
  buttons.forEach(({label,action})=>{const btn=document.createElement('button');btn.textContent=label;btn.onclick=action;div.append(btn);});
  $('#conversation').append(div);$('#chat-scroll').scrollTop=$('#chat-scroll').scrollHeight;
  sessionStorage.setItem('billy-chat-text',JSON.stringify([...$('#conversation').children].map(el=>({user:el.classList.contains('user'),text:el.querySelector('div')?.textContent}))));
}
try { const messages=JSON.parse(sessionStorage.getItem('billy-chat-text')||'[]');messages.forEach(m=>addMessage(m.text,m.user)); } catch{}
$('#chat-form').onsubmit=async e=>{
  e.preventDefault();let input=$('#chat-input').value.trim();if(!input)return;$('#chat-input').value='';addMessage(input,true);
  let q=input.replace(/^(find|search|look for|show me|show|open)\s+/i,'').replace(/\b(rfps?|opportunities|sources?|portals?)\b/gi,'').replace(/^\s*(in|for)\s+/i,'').trim();
  const stateMatch=q.match(/,?\s+(CA|California)$/i);let stateCode=stateMatch?'CA':'';if(stateMatch)q=q.slice(0,stateMatch.index).trim();
  if(/^california$/i.test(q)){stateCode='CA';q='';}
  try { const results=await api('/sources?'+new URLSearchParams({q,state:stateCode,limit:'5'}));
    if(!results.total){addMessage('I couldn’t find a source with that name. Try a city or agency, such as “Berkeley, CA.” For now, this conversation supports source lookup; open-ended drafting needs a model connection.');return;}
    addMessage(`I found ${results.total.toLocaleString()} source ${results.total===1?'record':'records'}${stateCode?' in California':''}. Choose a portal and I’ll open it in my browser.`,false,results.rows.map(row=>({label:`${row.name}, ${row.state} ↗`,action:()=>startResearch({source_id:row.id},row.name)})));
  }catch(err){toast(err.message);}
};
$('#chat-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('#chat-form').requestSubmit();}};
$('#start-california').onclick=()=>{showView('rfps');$('#state-filter').value='CA';offset=0;loadSources();};
$('#start-berkeley').onclick=()=>startResearch({source_id:5426},'Berkeley, California');
$('#start-import').onclick=()=>showView('company');
async function loadSources(){
  const request=++pendingSearch;
  try{const data=await api('/sources?'+new URLSearchParams({q:$('#source-search').value,state:$('#state-filter').value,offset:String(offset),limit:'30'}));if(request!==pendingSearch)return;sourceTotal=data.total;
    if($('#state-filter').options.length===1){data.states.forEach(s=>{const opt=document.createElement('option');opt.value=s;opt.textContent=s;$('#state-filter').append(opt);});}
    $('#indexed-count').textContent=`${data.indexed.toLocaleString()} sources indexed`;
    $('#source-count').textContent=data.total?`${offset+1}–${Math.min(offset+30,data.total)} of ${data.total.toLocaleString()} sources`:'No matching sources';
    $('#prev-page').disabled=offset===0;$('#next-page').disabled=offset+30>=data.total;
    $('#source-rows').innerHTML=data.rows.map(r=>`<tr><td>${esc(r.name)}<small>${esc(new URL(r.url).hostname)}</small></td><td>${esc(r.state)}</td><td>${r.checked?esc(date(r.checked)):'Not yet read'}</td><td><button class="read-source" data-source="${r.id}">Review ↗</button></td></tr>`).join('')||'<tr><td colspan="4">No sources match. Try a broader search.</td></tr>';
    document.querySelectorAll('[data-source]').forEach(btn=>btn.onclick=()=>{const row=data.rows.find(r=>String(r.id)===btn.dataset.source);startResearch({source_id:row.id},`${row.name}, ${row.state}`);});
  }catch(err){$('#source-rows').innerHTML='<tr><td colspan="4">Connect the workspace to load your source directory.</td></tr>';}
}
$('#source-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{offset=0;loadSources();},200);};
$('#state-filter').onchange=()=>{offset=0;loadSources();};$('#filter-california').onclick=()=>{$('#state-filter').value='CA';offset=0;loadSources();};
$('#prev-page').onclick=()=>{offset=Math.max(0,offset-30);loadSources();};$('#next-page').onclick=()=>{offset+=30;loadSources();};
function rfpsTab(directory){$('#directory-view').hidden=!directory;$('#opportunities-view').hidden=directory;$('#directory-tab').classList.toggle('selected',directory);$('#opportunities-tab').classList.toggle('selected',!directory);if(!directory)renderResearch();}
$('#directory-tab').onclick=()=>rfpsTab(true);$('#opportunities-tab').onclick=()=>rfpsTab(false);
async function startResearch(request,label){
  try{await api('/research',request);addMessage(`Review ${label}`,true);addMessage('Opening the source now. You can watch the page in my browser, or expand it to take over once it has loaded.');showView('chats');selectPanel('work');await refresh();}catch(err){toast(err.message);}
}
function renderResearch(){const result=state?.research;$('#opportunities-view').innerHTML=result?`<article class="research-card"><span class="eyebrow">SAVED PAGE · ${esc(date(result.checked))} · ${esc(when(result.checked))}</span><h3>${esc(result.title)}</h3><p>Read directly from the source in ${result.seconds}s. These are page links, not verified open opportunities.</p><a href="${esc(result.url)}" target="_blank" rel="noopener noreferrer">Open source ↗</a><div id="research-links"></div><details><summary>Read captured page text</summary><p style="white-space:pre-wrap">${esc(result.text)}</p></details></article>`:'<div class="empty-state">No pages reviewed yet. Choose a source and let Billy take a look.</div>';
  if(result){const list=$('#research-links');result.links.forEach(link=>{const row=document.createElement('div');row.className='source-link';const text=document.createElement('span');text.textContent=link.title;const button=document.createElement('button');button.textContent='Review ↗';button.onclick=()=>startResearch({url:link.url},link.title);row.append(text,button);list.append(row);});}}
function renderDocuments(){const docs=state?.documents||[];$('#documents').innerHTML=docs.map(d=>`<article class="document-card"><h3>${esc(d.name)}</h3><p>Original PDF pages ${d.first_page}–${d.last_page} · imported ${esc(date(d.added))}</p><button data-document="${d.id}">Review extracted pages ↗</button></article>`).join('');bindDocuments();}
function bindDocuments(){document.querySelectorAll('[data-document]').forEach(btn=>btn.onclick=()=>openDocument(btn.dataset.document));}
async function openDocument(id){try{const doc=await api('/documents/'+id);$('#document-title').textContent=doc.name;$('#document-pages').innerHTML=doc.pages.map(p=>`<section class="pdf-page"><a href="${API}/api/documents/${doc.id}/pdf#page=${p.page}" target="_blank" rel="noopener noreferrer">Original PDF · page ${p.page} ↗</a><pre>${esc(p.text||'No extractable text on this page. Open the original PDF to inspect it.')}</pre></section>`).join('');$('#document-dialog').showModal();}catch(err){toast(err.message);}}
$('#close-document').onclick=()=>$('#document-dialog').close();
$('#proposal-file').onchange=()=>{$('#file-name').textContent=$('#proposal-file').files[0]?.name||'Up to 25 MB · up to 100 pages';};
$('#import-form').onsubmit=async e=>{e.preventDefault();const file=$('#proposal-file').files[0];if(!file)return;const data=new FormData();data.append('file',file);data.append('first_page',$('#first-page').value||'1');data.append('last_page',$('#last-page').value||'0');$('#import-submit').disabled=true;$('#import-submit').textContent='Extracting pages…';try{const result=await api('/documents',data);await refresh();renderDocuments();toast(`Imported ${result.pages} pages. Original page references preserved.`);}catch(err){toast(err.message);}finally{$('#import-submit').disabled=false;$('#import-submit').textContent='Import response ↗';}};
function renderArtifacts(){let html=(state?.documents||[]).map(d=>`<article class="document-card"><span class="eyebrow">IMPORTED RESPONSE</span><h3>${esc(d.name)}</h3><p>PDF pages ${d.first_page}–${d.last_page}. Extracted text and original file.</p><button data-document="${d.id}">Open pages ↗</button></article>`).join('');if(state?.research)html+=`<article class="research-card"><span class="eyebrow">SAVED RESEARCH</span><h3>${esc(state.research.title)}</h3><p>Captured ${esc(date(state.research.checked))} at ${esc(when(state.research.checked))}</p><button id="artifact-research">Open research ↗</button></article>`;$('#artifact-list').innerHTML=html||'<div class="empty-state">Your work will collect here. Import a response or read an RFP source to create your first artifact.</div>';bindDocuments();if($('#artifact-research'))$('#artifact-research').onclick=()=>{showView('rfps');rfpsTab(false);};}
function approvalHTML(p){return `<article class="decision-card"><strong>${esc(p.title)}</strong><p>${esc(p.detail)}</p><p>${esc(p.url)}</p><div class="decision-actions"><button class="approve" data-approve="true">${p.kind==='form'?'Submit form':'Allow once'}</button><button data-approve="false">Decline</button></div></article>`;}
function renderDecisions(){const pending=state?.browser.pending;$('#decision-count').textContent=pending?'1':'';$('#pending-decisions').innerHTML=pending?approvalHTML(pending):'<div class="empty-state">Nothing waiting on you.<br>Billy will pause here before sending or submitting.</div>';$('#dialog-approval').innerHTML=pending?approvalHTML(pending):'';document.querySelectorAll('[data-approve]').forEach(btn=>btn.onclick=async()=>{try{await api('/browser/approval',{id:pending.id,approved:btn.dataset.approve==='true'});await refresh();toast(btn.dataset.approve==='true'?'Approved once. Repeat the intended action within 30 seconds.':'Action declined.');}catch(err){toast(err.message);}});const approvals=(state?.events||[]).filter(e=>e.kind==='approval');$('#approval-history').innerHTML=approvals.length?approvals.map(e=>`<div class="history-item"><strong>${esc(e.title)}</strong>${esc(e.detail)}<br>${esc(when(e.at))}</div>`).join(''):'<div class="empty-state">Your approvals will be recorded here.</div>';}
async function refresh(){try{const next=await api('/state');state=next;$('#connection-notice').hidden=true;$('#billy-status').textContent=next.browser.status;$('#status-dot').className='status-dot connected'+(next.browser.busy?' working':'');$('#vm-label').textContent=next.environment;$('#environment-setting').textContent=next.environment+' · browser, saved research and document storage';$('#backend-status').textContent='Connected';$('#indexed-count').textContent=`${next.total.toLocaleString()} sources indexed`;
  $('#activity-log').innerHTML=next.events.length?next.events.map(e=>`<li class="${esc(e.kind)}"><strong>${esc(e.title)}</strong><p>${esc(e.kind==='error'?e.detail.split('\n')[0]:e.detail)}</p><time>${esc(when(e.at))}</time></li>`).join(''):'<li><strong>Ready when you are</strong><p>Pick a source or import a previous response to get started.</p></li>';
  if(initialized){const newEvents=next.events.filter(e=>e.id>lastEvent).reverse();newEvents.forEach(e=>{if(e.kind==='done'&&e.title==='Page read and saved')addMessage(`I’ve read and saved the page: ${next.research?.title||e.detail}. Choose a relevant link to continue, or inspect the browser.`,false,[{label:'Review page links ↗',action:()=>{showView('rfps');rfpsTab(false);}}]);if(e.kind==='error')addMessage(e.detail);});}
  lastEvent=Math.max(lastEvent,...next.events.map(e=>e.id));initialized=true;
  $('#take-control-small').disabled=!next.browser.ready||next.browser.busy;
  $('#mini-url').textContent=next.browser.url&&next.browser.url!=='about:blank'?next.browser.url:'A fresh page, ready for work';$('#browser-address').textContent=next.browser.url||'No page open';
  const mine=next.browser.controller==='you';$('#browser-owner').textContent=mine?'You are in control':'Billy is in control';$('#take-control').textContent=mine?'Hand back to Billy':'Take control';$('#take-control').disabled=next.browser.busy||!next.browser.ready;$('#remote-screen').classList.toggle('in-control',mine);$('#browser-note').textContent=mine?'Click the page to focus a field. Type below, or use your keyboard. Submit actions still require approval.':'You can watch Billy here. Take control to interact with this session.';
  ['#browser-back','#browser-reload','#browser-text','#send-browser-text','#browser-enter','#browser-scroll-up','#browser-scroll-down'].forEach(s=>$(s).disabled=!mine||next.browser.busy);
  renderDecisions();if(currentView==='company')renderDocuments();if(currentView==='artifacts')renderArtifacts();if(currentView==='rfps'&&!$('#opportunities-view').hidden)renderResearch();
}catch(err){$('#connection-notice').hidden=false;$('#connection-notice').textContent=local?'Billy’s workspace is not connected. Start the local service or reconnect the VM tunnel. Your saved work is retained.':'Open your connected workspace to use Billy’s browser and private documents.';$('#billy-status').textContent='Workspace disconnected';$('#status-dot').className='status-dot';$('#backend-status').textContent='Disconnected';}}
async function refreshFrame(){if(!state?.browser.ready||pendingFrame||document.hidden)return;pendingFrame=true;try{const res=await fetch(API+'/api/browser/frame');if(res.status!==200)return;const blob=await res.blob();const old=frameURL;frameURL=URL.createObjectURL(blob);$('#browser-thumbnail').src=frameURL;$('#browser-full').src=frameURL;$('#browser-thumbnail').hidden=false;$('#browser-empty').hidden=true;$('#full-empty').hidden=true;if(old)URL.revokeObjectURL(old);}catch{}finally{pendingFrame=false;}}
function expandBrowser(){ $('#browser-dialog').showModal();refreshFrame(); }
$('#expand-browser').onclick=expandBrowser;$('#close-browser').onclick=()=>$('#browser-dialog').close();
async function takeControl(){try{await api('/browser/control',{controller:state.browser.controller==='you'?'billy':'you'});await refresh();}catch(err){toast(err.message);}}
$('#take-control').onclick=takeControl;$('#take-control-small').onclick=async()=>{expandBrowser();if(state.browser.controller!=='you')await takeControl();};
async function browserAction(data){try{await api('/browser/action',data);await refresh();await refreshFrame();}catch(err){toast(err.message);}}
$('#browser-full').onclick=e=>{if(state?.browser.controller!=='you')return;const r=e.target.getBoundingClientRect();const ratio=Math.min(r.width/1280,r.height/800);const x=(e.clientX-r.left-(r.width-1280*ratio)/2)/ratio,y=(e.clientY-r.top-(r.height-800*ratio)/2)/ratio;if(x>=0&&x<=1280&&y>=0&&y<=800)browserAction({kind:'click',x,y});};
$('#remote-screen').onkeydown=e=>{if(state?.browser.controller!=='you'||e.key==='Escape')return;const keys=['Enter','Tab','Backspace','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'];if(keys.includes(e.key)){e.preventDefault();browserAction({kind:'key',text:e.key});}else if(e.key.length===1&&!e.metaKey&&!e.ctrlKey){e.preventDefault();browserAction({kind:'type',text:e.key});}};
$('#send-browser-text').onclick=()=>{const text=$('#browser-text').value;if(text){browserAction({kind:'type',text});$('#browser-text').value='';}};
$('#browser-text').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();$('#send-browser-text').click();}};
$('#browser-enter').onclick=()=>browserAction({kind:'key',text:'Enter'});$('#browser-back').onclick=()=>browserAction({kind:'back'});$('#browser-reload').onclick=()=>browserAction({kind:'reload'});$('#browser-scroll-up').onclick=()=>browserAction({kind:'scroll',delta:-600});$('#browser-scroll-down').onclick=()=>browserAction({kind:'scroll',delta:600});
const video=$('#billy-video');$('#billy-motion').onclick=()=>{if(video.paused){video.play().catch(()=>{});$('#billy-motion').textContent='Ⅱ';$('#billy-motion').setAttribute('aria-label','Pause Billy animation');}else{video.pause();$('#billy-motion').textContent='▷';$('#billy-motion').setAttribute('aria-label','Play Billy animation');}};
if(!matchMedia('(prefers-reduced-motion: reduce)').matches)$('#billy-motion').click();
await refresh();await loadSources();setInterval(refresh,2500);setInterval(refreshFrame,1600);
