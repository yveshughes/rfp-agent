import {createAutopilot} from './autopilot.js?v=dismiss-summary-1';
import {createDiscussionAgenda} from './discussion-agenda.js?v=friendly-topics-1';
import {createDocumentReview} from './document-review.js?v=1';
import {createChatAttachments} from './chat-attachments.js?v=pdf-thumbnail-1';
import {createChatSuggestions,suggestedPrompts} from './chat-suggestions.js?v=website-prompt-1';
import {connectWorkspace} from './workspaces.js?v=profile-colors-1';
import {createAgentChat} from './agent-chat.js?v=single-chat-1';
import {createOpportunityFeed} from './opportunities.js?v=response-canvas-1';
import {createDiscussion} from './discuss.js?v=agenda-opener-1';
import {createRFPDetail} from './rfp-detail.js?v=response-canvas-1';
import {createCompanyProfile} from './company.js?v=direct-edits-1';
import {createBillyMotion,setupMotionPreview,resolveBillyPanel} from './billy-motion.js?v=phone-conversation-1';
import {createLiveVoice} from './live-voice.js?v=1';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const local = ['localhost','127.0.0.1'].includes(location.hostname);
const API_ORIGIN = local && location.port === '8080' ? 'http://127.0.0.1:8081' : '';
const companyWorkspace = await connectWorkspace(API_ORIGIN, toast);
const API = companyWorkspace.api;
const storageKey = key => `billy-${companyWorkspace.id}-${key}`;
let state = null, offset = 0, sourceTotal = 0, currentView = 'chats', lastEvent = 0, initialized = false, frameURL = null, pendingFrame = false, searchTimer, pendingSearch = 0;
let rfpRows=[], rfpStatuses=[], rfpSort='updated', rfpAscending=false, editingRFP=null, openingRFP=0;
const views = {chats:'Chats',rfps:'RFPs',sources:'Sources',company:'Company Profile',artifacts:'Artifacts',settings:'Settings'};
let navigationAtLoad=null, navigationInteractions=0;
try{
  const [path,query]=window.location.hash.slice(1).split('?'),parts=path.split('/').filter(Boolean);
  if(parts.length)navigationAtLoad={view:parts[0],companySection:parts[0]==='company'?parts[1]:null,rfpList:parts[1],rfp:parts[0]==='rfps'?parts[2]:null,rfpTab:parts[3],panel:new URLSearchParams(query).get('panel')};
}catch{}
for(const event of ['pointerdown','keydown'])document.addEventListener(event,()=>navigationInteractions++,{capture:true});
function rememberNavigation(){
  const selected=s=>document.querySelector(s);
  const saved={view:currentView,companySection:selected('[data-company-section][aria-selected="true"]')?.dataset.companySection,
    rfpList:$('#pipeline-view').hidden?'all':'mine',rfp:$('#rfp-detail-page').hidden?null:(editingRFP||'new'),
    rfpTab:selected('[data-rfp-tab][aria-selected="true"]')?.dataset.rfpTab,
    panel:selected('[data-panel][aria-selected="true"]')?.dataset.panel};
  const parts=[saved.view];
  if(saved.view==='company')parts.push(saved.companySection||'company');
  if(saved.view==='rfps'){parts.push(saved.rfpList);if(saved.rfp)parts.push(saved.rfp,saved.rfpTab||'files');}
  const hash='#/'+parts.map(encodeURIComponent).join('/')+(saved.panel&&saved.panel!=='work'?'?panel='+saved.panel:'');
  if(window.location.hash!==hash)history.replaceState(null,'',hash);
}
window.addEventListener('pagehide',rememberNavigation);
document.addEventListener('click',()=>queueMicrotask(rememberNavigation));

const when = timestamp => new Date(timestamp * 1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});
const date = timestamp => new Date(timestamp * 1000).toLocaleDateString([], {month:'short',day:'numeric'});
const billyMotion=createBillyMotion();
let documentRequests=0, workspaceConnected=false, discussionState=null, voiceState=null, agentState=null, agentActivity=null, lastAutoPanel=null;
const updateBillyMotion=(forcePanel=false)=>{
  const options={connected:workspaceConnected,documentRequests,discussionState:voiceState||discussionState||agentState,agentActivity,autopilotRunning:reviewSnapshot?.run?.autopilot&&reviewSnapshot?.run?.status==='running',chatOpen:currentView==='chats'};
  const resolved=billyMotion.update(state,options);
  document.querySelector('[data-panel="discuss"]').hidden=resolved.motion==='idle';
  const panel=resolveBillyPanel(state,options);
  // Follow real transitions; a manual tab choice remains usable between them.
  if(panel && (forcePanel || panel!==lastAutoPanel))selectPanel(panel);
  lastAutoPanel=panel;
};
setupMotionPreview();
const rfpDetail=createRFPDetail({api,esc,toast,getDocuments:()=>state?.documents||[],onSaved:result=>{loadRFPs();if(editingRFP===result.rfp.id)autopilot?.setRFP(result.rfp);},openDiscussion:(context,label)=>discussion.open(context,label)});
const opportunityFeed=createOpportunityFeed({api,esc,toast,openRFP,showSources:()=>showView('sources'),showCompany:()=>showView('company'),openDocument});
const companyProfile=createCompanyProfile({api,esc,toast,showView,openDocument,getState:()=>state,openDiscussion:(context,label)=>discussion.open(context,label)});
const discussion=createDiscussion({api,esc,toast,showView,sendAgent:(text,context)=>sendContextualMessage(text,context),onState:value=>{discussionState=value;updateBillyMotion();}});
const discussionAgenda=createDiscussionAgenda({api,esc,onSelect:item=>discussion.open(item.context,item.label,item.question)});
let chatSuggestions,autopilot;
const documentReview=createDocumentReview({esc,resourceURL:path=>API+path,openDocument,openBrowser:expandBrowser});
let reviewSnapshot=null;
const agentChat=createAgentChat({api,esc,toast,openReview:id=>autopilot.openReview(id),openDocument,openCompany:()=>showView('company'),onReply:text=>{if(text&&!document.hidden&&currentView==='chats'&&$('#discuss-read-aloud').checked&&'speechSynthesis' in window){speechSynthesis.cancel();const speech=new SpeechSynthesisUtterance(text);speech.rate=1.05;speechSynthesis.speak(speech);}},openRFP,resourceURL:path=>API+path,onState:(value,activity,snapshot)=>{agentState=value;agentActivity=activity;reviewSnapshot=snapshot;updateBillyMotion();documentReview.update(snapshot,state,activity);chatSuggestions?.update();autopilot?.update(snapshot);},onPipelineChange:()=>loadRFPs(),onSaved:async()=>{await companyProfile.load();await loadRFPs();await discussionAgenda.refresh(true);},importDocument:()=>companyProfile.documents()});
autopilot=createAutopilot({api,esc,toast,storageKey,resourceURL:path=>API+path,onChange:async()=>{await agentChat.poll();await loadRFPs();selectPanel('work');}});
// Live voice: Gemini listens and speaks; ask_billy routes every workspace question through the agent.
const liveVoice=createLiveVoice({api,toast,agentChat,onState:value=>{voiceState=value;updateBillyMotion();},elements:{button:$('#call-billy'),bar:$('#voice-call'),status:$('#voice-call-status'),transcript:$('#voice-call-transcript'),hangup:$('#voice-hangup')}});
window.billyVoice=liveVoice;
const chatAttachments=createChatAttachments({api,esc,toast,onPipelineChange:()=>loadRFPs(),onSaved:async()=>{await refresh();renderDocuments();}});
chatSuggestions=createChatSuggestions({input:$('#chat-input'),getCandidates:()=>suggestedPrompts(agentChat.getSnapshot())});
function toast(message) { $('#toast').textContent=message; $('#toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('#toast').hidden=true,6500); }
async function api(path, data) {
  const opts = data === undefined ? {} : {method:'POST',headers:{'X-Billy-Client':'workspace'}};
  if(data instanceof FormData) opts.body=data;
  else if(data!==undefined){opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(data);}
  const reading=data!==undefined && (path==='/documents' || path==='/company/attachments' || /^\/rfps\/[^/]+\/documents\/download$/.test(path));
  if(reading){documentRequests++;updateBillyMotion();}
  try {
  const response=await fetch(API+'/api'+path,opts);
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(typeof detail==='string'?detail:`Workspace request failed (${response.status}).`);}
  return await response.json();
  } finally {if(reading){documentRequests--;updateBillyMotion();}}
}
function showView(name) {
  if(name!=='rfps')++openingRFP;
  currentView=name;discussion.view(name);updateBillyMotion(true);
  Object.keys(views).forEach(view=>{ $('#view-'+view).hidden=view!==name; document.querySelector(`[data-view="${view}"]`).classList.toggle('selected',view===name); });
  $('#view-title').textContent=views[name];
  $('#profile-progress').hidden=name!=='company';
  $('#indexed-count').hidden=name!=='sources';
  if(name==='rfps'){loadRFPs();if(!$('#opportunity-feed').hidden)opportunityFeed.load();}
  if(name==='sources')loadSources();
  if(name==='company'){renderDocuments();companyProfile.load();}
  if(name==='artifacts') renderArtifacts();
}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>showView(button.dataset.view)));
$('#profile-shortcut').onclick=()=>{$('#workspace-menu').hidden=true;$('#workspace-switcher').setAttribute('aria-expanded','false');showView('company');};
$('#collapse-nav').onclick=()=>{const collapsed=$('#workspace').classList.toggle('nav-collapsed');$('#collapse-nav').setAttribute('aria-label',collapsed?'Expand navigation':'Collapse navigation');};
function selectPanel(name){if(name==='discuss'&&document.querySelector('[data-panel="discuss"]').hidden)name='work';document.querySelectorAll('[data-panel]').forEach(x=>x.setAttribute('aria-selected',String(x.dataset.panel===name)));for(const panel of ['discuss','work','decisions'])$('#panel-'+panel).hidden=name!==panel;}
document.querySelectorAll('[data-panel]').forEach(button=>button.onclick=()=>selectPanel(button.dataset.panel));
function addMessage(text, user=false, buttons=[]) {
  $('#welcome').hidden=true;
  const div=document.createElement('div');div.className='message'+(user?' user':'');
  if(!user){const label=document.createElement('span');label.className='message-name';label.textContent='BILLY';div.append(label);}
  const content=document.createElement('div');content.textContent=text;div.append(content);
  buttons.forEach(({label,action})=>{const btn=document.createElement('button');btn.textContent=label;btn.onclick=action;div.append(btn);});
  $('#conversation').append(div);$('#chat-scroll').scrollTop=$('#chat-scroll').scrollHeight;
  sessionStorage.setItem(storageKey('chat-text'),JSON.stringify([...$('#conversation').children].map(el=>({user:el.classList.contains('user'),text:el.querySelector('div')?.textContent}))));
}
try { const messages=JSON.parse(sessionStorage.getItem(storageKey('chat-text'))||'[]');messages.forEach(m=>addMessage(m.text,m.user)); } catch{}
async function sendContextualMessage(text,context={},documents=[]) {
  const sent=await agentChat.send(text,context,documents);
  if(sent)await agentChat.poll();
  return sent;
}
$('#chat-form').onsubmit=async e=>{
  e.preventDefault();const form=$('#chat-form'),input=$('#chat-input').value.trim();
  if(form.dataset.uploading==='true'||(!input&&!chatAttachments.hasFiles()))return;
  if(agentChat.getSnapshot()?.run?.status==='running'){toast('Billy is working. Wait for his next question.');return;}
  form.dataset.uploading='true';$('#chat-input').disabled=true;form.querySelector('button[type="submit"]').disabled=true;chatAttachments.setBusy(true);
  try{
    const documents=chatAttachments.hasFiles()?await chatAttachments.upload():[];
    const text=input||'Use these attachments to update my company profile with supported details.';
    const sent=await agentChat.send(text,undefined,documents);
    if(sent){$('#chat-input').value='';chatAttachments.clear();}
  }catch(error){toast(error.message);}
  finally{form.dataset.uploading='false';$('#chat-input').disabled=false;chatAttachments.setBusy(false);form.querySelector('button[type="submit"]').disabled=agentChat.getSnapshot()?.run?.status==='running';chatSuggestions.update();}
};
$('#company-attach-files').onclick=()=>{showView('chats');$('#chat-files').click();$('#chat-input').focus();};
$('#chat-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#chat-form').requestSubmit();}};
const selectedStates=new Set();
function updateStateFilter(){
  const codes=[...selectedStates].sort();
  $('#state-filter-label').textContent=codes.length?(codes.length<=3?codes.join(', '):`${codes.length} states`):'All states';
  $('#state-filter-summary').setAttribute('aria-label',`Filter by states: ${codes.join(', ')||'All states'}`);
  $('#state-filter-options').querySelectorAll('input').forEach(input=>{input.checked=selectedStates.has(input.value);});
}
function applyStateFilter(){updateStateFilter();offset=0;loadSources();}
function closeStateFilter(){ $('#state-filter').open=false; }
$('#state-filter-options').onchange=e=>{
  const input=e.target;if(!input.matches('input[type="checkbox"]'))return;
  if(input.checked)selectedStates.add(input.value);else selectedStates.delete(input.value);
  applyStateFilter();
};
$('#state-filter-clear').onclick=()=>{selectedStates.clear();applyStateFilter();};
$('#state-filter-done').onclick=()=>{closeStateFilter();$('#state-filter-summary').focus();};
$('#state-filter').onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();closeStateFilter();$('#state-filter-summary').focus();}};
document.addEventListener('click',e=>{if(!$('#state-filter').contains(e.target))closeStateFilter();});
document.addEventListener('focusin',e=>{if(!$('#state-filter').contains(e.target))closeStateFilter();});
$('#start-california').onclick=()=>{selectedStates.clear();selectedStates.add('CA');updateStateFilter();offset=0;showView('sources');};
async function loadCaliforniaCount(){
  // The welcome tile reports the directory's actual California count, never a fixed number.
  try{const data=await api('/sources?'+new URLSearchParams({state:'CA',limit:'1'}));$('#start-california-count').textContent=data.total?`Browse ${data.total.toLocaleString()} source records`:'No California sources loaded yet';}
  catch{$('#start-california-count').textContent='Browse California source records';}
}
function draftStarterPrompt(prompt){
  const input=$('#chat-input');if(input.disabled)return;
  if(!input.value.includes(prompt))input.value=input.value.trim()?input.value.trim()+'\n\n'+prompt:prompt;
  input.focus();input.setSelectionRange(input.value.length,input.value.length);
  input.dispatchEvent(new Event('input',{bubbles:true}));
}
$('#start-website').onclick=()=>draftStarterPrompt('Review my company website and extract information about my company to build my profile for future proposals. Include company details, services, experience, team, and qualifications supported by the website.');
$('#start-import').onclick=()=>draftStarterPrompt('Review my previous RFP response and use it to build my company profile for future proposals. Extract the company details, services, experience, team, and qualifications supported by the document.');
async function loadSources(){
  const request=++pendingSearch;
  try{const data=await api('/sources?'+new URLSearchParams({q:$('#source-search').value,state:[...selectedStates].sort().join(','),offset:String(offset),limit:'30',watched:String($('#watched-only').checked)}));if(request!==pendingSearch)return;sourceTotal=data.total;$('#watch-count').textContent=`${data.watch_count} / ${data.watch_limit} sources watched`;
    if(!$('#state-filter-options').children.length){
      $('#state-filter-options').innerHTML=data.states.filter(Boolean).map(s=>`<label><input type="checkbox" value="${esc(s)}"><span>${esc(s)}</span></label>`).join('');
      updateStateFilter();
    }
    $('#indexed-count').textContent=`${data.indexed.toLocaleString()} sources indexed`;
    $('#source-count').textContent=data.total?`${offset+1}–${Math.min(offset+30,data.total)} of ${data.total.toLocaleString()} sources`:'No matching sources';
    $('#prev-page').disabled=offset===0;$('#next-page').disabled=offset+30>=data.total;
    $('#source-rows').innerHTML=data.rows.map(r=>`<tr><td>${esc(r.name)}<small>${esc(new URL(r.url).hostname)}</small></td><td>${esc(r.state)}</td><td>${r.checked?esc(date(r.checked)):'Not yet read'}</td><td><button class="read-source" data-source="${r.id}">Review ↗</button></td><td><button data-watch="${r.id}" aria-pressed="${r.watched}">${r.watched?'Watching ✓':'Watch'}</button></td></tr>`).join('')||'<tr><td colspan="5">No sources match. Try a broader search.</td></tr>';
    document.querySelectorAll('[data-watch]').forEach(btn=>btn.onclick=async()=>{btn.disabled=true;try{await api('/sources/'+btn.dataset.watch+'/watch',{watched:btn.getAttribute('aria-pressed')!=='true'});await loadSources();}catch(err){btn.disabled=false;toast(err.message);}});
    document.querySelectorAll('[data-source]').forEach(btn=>btn.onclick=()=>{const row=data.rows.find(r=>String(r.id)===btn.dataset.source);startResearch({source_id:row.id},`${row.name}, ${row.state}`);});
  }catch(err){$('#source-rows').innerHTML='<tr><td colspan="4">Connect the workspace to load your source directory.</td></tr>';}
}
$('#watched-only').onchange=()=>{offset=0;loadSources();};
$('#source-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{offset=0;loadSources();},200);};
$('#filter-california').onclick=()=>{selectedStates.add('CA');applyStateFilter();};
$('#prev-page').onclick=()=>{offset=Math.max(0,offset-30);loadSources();};$('#next-page').onclick=()=>{offset+=30;loadSources();};
function rfpsTab(directory){if(directory){showView('sources');return;}showAllOpportunities();}
async function startResearch(request,label){
  if(request.url && /\.pdf(?:[?#]|$)/i.test(request.url)){openRFP(null,{title:label,url:request.url});toast('Save this RFP, then download its original PDF below.');return;}
  try{await api('/research',request);addMessage(`Review ${label}`,true);addMessage('Opening the source now. You can watch the page in my browser, or expand it to take over once it has loaded.');showView('chats');await refresh();}catch(err){toast(err.message);}
}

function documentKind(d){return !d.media_type||d.media_type==='application/pdf'?'PDF':d.media_type.startsWith('image/')?'Image':d.media_type.includes('wordprocessingml')?'Word document':'Text document';}
function renderDocuments(){const docs=(state?.documents||[]).filter(d=>!d.rfp_id);$('#documents').innerHTML=docs.map(d=>`<article class="document-card"><h3>${esc(d.name)}</h3><p>${documentKind(d)} · saved ${esc(date(d.added))}</p><button data-document="${d.id}">Open document ↗</button></article>`).join('');bindDocuments();}
function bindDocuments(){document.querySelectorAll('[data-document]').forEach(btn=>btn.onclick=()=>openDocument(btn.dataset.document));}
async function openDocument(id,page=null){try{
  const doc=await api('/documents/'+id),pdf=documentKind(doc)==='PDF',image=doc.media_type?.startsWith('image/');
  const original=API+'/api/documents/'+encodeURIComponent(doc.id)+'/file';
  $('#document-title').textContent=doc.name;
  $('#document-pages').innerHTML=`<div class="document-actions"><a href="${original}${pdf&&page?`#page=${page}`:''}" target="_blank" rel="noopener">Open original ↗</a><a href="${original}?download=true">Download original ↓</a></div><p class="muted">${esc(doc.extraction_note||(pdf?`Extracted pages ${doc.first_page}–${doc.last_page}. The complete original is retained.`:'The complete original is retained.'))}</p>${image?`<img class="document-image" src="${original}" alt="${esc(doc.name)}">`:''}`+doc.pages.map(p=>`<section class="pdf-page">${pdf?`<a href="${original}#page=${p.page}" target="_blank" rel="noopener noreferrer">Original PDF · page ${p.page} ↗</a>`:`<strong>${image?'Recognized image text':'Text excerpt '+p.page}</strong>`}<pre>${esc(p.text||'No readable text found. Open the original to review it.')}</pre></section>`).join('');
  $('#document-dialog').showModal();
}catch(err){toast(err.message);}}
$('#close-document').onclick=()=>$('#document-dialog').close();
$('#proposal-file').onchange=()=>{$('#file-name').textContent=$('#proposal-file').files[0]?.name||'Up to 25 MB · up to 100 pages';};
$('#import-form').onsubmit=async e=>{e.preventDefault();const file=$('#proposal-file').files[0];if(!file)return;const data=new FormData();data.append('file',file);data.append('first_page',$('#first-page').value||'1');data.append('last_page',$('#last-page').value||'0');$('#import-submit').disabled=true;$('#import-submit').textContent='Extracting pages…';try{const result=await api('/documents',data);await refresh();renderDocuments();if(agentChat.hasRun()){await agentChat.send(`Use the previous response I just uploaded: document ${result.id}. Read its extracted pages, identify reusable evidence, and compare it with the selected RFP.`);showView('chats');}toast(`Imported ${result.pages} pages. Original page references preserved.`);}catch(err){toast(err.message);}finally{$('#import-submit').disabled=false;$('#import-submit').textContent='Save document ↗';}};
async function renderArtifacts(){let pdfs=[];try{pdfs=await api('/response-pdfs');}catch{}let html=pdfs.map(p=>`<article class="document-card"><span class="eyebrow">RESPONSE PDF</span><h3>${esc(p.name)}</h3><p>${p.pages} pages · ${p.stale?'Earlier version; sections have changed':'Saved review copy'}</p><a href="${esc(API+'/api/response-pdfs/'+encodeURIComponent(p.id))}" target="_blank" rel="noopener">Open PDF ↗</a></article>`).join('')+(state?.documents||[]).map(d=>`<article class="document-card"><span class="eyebrow">${d.rfp_id?'RFP ORIGINAL':'COMPANY DOCUMENT'}</span><h3>${esc(d.name)}</h3><p>${documentKind(d)} · Original file and readable text.</p><button data-document="${d.id}">Open document ↗</button></article>`).join('');if(state?.research)html+=`<article class="research-card"><span class="eyebrow">SAVED RESEARCH</span><h3>${esc(state.research.title)}</h3><p>Captured ${esc(date(state.research.checked))} at ${esc(when(state.research.checked))}</p><button id="artifact-research">Open research ↗</button></article>`;$('#artifact-list').innerHTML=html||'<div class="empty-state">Your work will collect here. Import a response or read an RFP source to create your first artifact.</div>';bindDocuments();if($('#artifact-research'))$('#artifact-research').onclick=()=>{const r=state.research;$('#document-title').textContent=r.title;$('#document-pages').innerHTML=`<p><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">Open source ↗</a></p><pre style="white-space:pre-wrap">${esc(r.text)}</pre>`;$('#document-dialog').showModal();};}
function approvalHTML(p){return `<article class="decision-card"><strong>${esc(p.title)}</strong><p>${esc(p.detail)}</p><p>${esc(p.url)}</p><div class="decision-actions"><button class="approve" data-approve="true">${p.kind==='form'?'Submit form':'Allow once'}</button><button data-approve="false">Decline</button></div></article>`;}
function renderDecisions(){const pending=state?.browser.pending;$('#decision-count').textContent=pending?'1':'';$('#pending-decisions').innerHTML=pending?approvalHTML(pending):'<div class="empty-state">Nothing waiting on you.<br>Billy will pause here before sending or submitting.</div>';$('#dialog-approval').innerHTML=pending?approvalHTML(pending):'';document.querySelectorAll('[data-approve]').forEach(btn=>btn.onclick=async()=>{try{await api('/browser/approval',{id:pending.id,approved:btn.dataset.approve==='true'});await refresh();toast(btn.dataset.approve==='true'?'Approved once. Repeat the intended action within 30 seconds.':'Action declined.');}catch(err){toast(err.message);}});const approvals=(state?.events||[]).filter(e=>e.kind==='approval');$('#approval-history').innerHTML=approvals.length?approvals.map(e=>`<div class="history-item"><strong>${esc(e.title)}</strong>${esc(e.detail)}<br>${esc(when(e.at))}</div>`).join(''):'<div class="empty-state">Your approvals will be recorded here.</div>';}
async function refresh(){try{const next=await api('/state');state=next;workspaceConnected=true;updateBillyMotion();documentReview.update(reviewSnapshot,state,agentActivity);$('#connection-notice').hidden=true;$('#vm-label').textContent=next.environment;$('#environment-setting').textContent=next.environment+' · browser, saved research and document storage';$('#backend-status').textContent='Connected';$('#indexed-count').textContent=`${next.total.toLocaleString()} sources indexed`;
  $('#activity-log').innerHTML=next.events.length?next.events.map(e=>`<li class="${esc(e.kind)}"><strong>${esc(e.title)}</strong><p>${esc(e.kind==='error'?e.detail.split('\n')[0]:e.detail)}</p><time>${esc(when(e.at))}</time></li>`).join(''):'<li><strong>Ready when you are</strong><p>Pick a source or import a previous response to get started.</p></li>';
  if(initialized){const newEvents=next.events.filter(e=>e.id>lastEvent).reverse();newEvents.forEach(e=>{if(e.kind==='done'&&e.title==='Page read and saved')addMessage(`I’ve read and saved the page: ${next.research?.title||e.detail}. Choose a relevant link to continue, or inspect the browser.`,false,[{label:'View opportunities ↗',action:()=>{showView('rfps');rfpsTab(false);}}]);if(e.kind==='error')addMessage(e.detail);});}
  lastEvent=Math.max(lastEvent,...next.events.map(e=>e.id));initialized=true;
  $('#take-control-small').disabled=!next.browser.ready||next.browser.busy;
  $('#mini-url').textContent=next.browser.url&&next.browser.url!=='about:blank'?next.browser.url:'A fresh page, ready for work';$('#browser-address').textContent=next.browser.url||'No page open';
  const mine=next.browser.controller==='you';$('#browser-owner').textContent=mine?'You are in control':'Billy is in control';$('#take-control').textContent=mine?'Hand back to Billy':'Take control';$('#take-control').disabled=next.browser.busy||!next.browser.ready;$('#remote-screen').classList.toggle('in-control',mine);$('#browser-note').textContent=mine?'Click the page to focus a field. Type below, or use your keyboard. Submit actions still require approval.':'You can watch Billy here. Take control to interact with this session.';
  ['#browser-back','#browser-reload','#browser-text','#send-browser-text','#browser-enter','#browser-scroll-up','#browser-scroll-down'].forEach(s=>$(s).disabled=!mine||next.browser.busy);
  agentChat.poll();discussionAgenda.refresh();renderDecisions();if(currentView==='company')renderDocuments();if(currentView==='artifacts')renderArtifacts();if(currentView==='rfps'&&!$('#opportunity-feed').hidden)opportunityFeed.load();
}catch(err){$('#connection-notice').hidden=false;$('#connection-notice').textContent=local?'Billy’s workspace is not connected. Start the local service or reconnect the VM tunnel. Your saved work is retained.':'This is Billy’s private workspace. It runs on a Vultr VM over a private connection and is shown live during judging; the public site cannot reach it.';workspaceConnected=false;updateBillyMotion();$('#backend-status').textContent='Disconnected';}}
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
await refresh();await companyProfile.load();await loadSources();loadCaliforniaCount();setInterval(refresh,2500);setInterval(refreshFrame,1600);setInterval(()=>{if(!document.hidden&&!$('#profile-dialog').open)companyProfile.load();},10000);


async function loadRFPs(){try{const data=await api('/rfps');rfpRows=data.rows;rfpStatuses=data.statuses;const filter=$('#rfp-status-filter'), selected=filter.value;filter.innerHTML='<option value="">All statuses</option>'+rfpStatuses.map(s=>`<option>${esc(s)}</option>`).join('');filter.value=selected;if(!$('#rfp-status').options.length)$('#rfp-status').innerHTML=rfpStatuses.map(s=>`<option>${esc(s)}</option>`).join('');renderRFPs();}catch(err){toast(err.message);}}
function showPipeline(){++openingRFP;rfpDetail.back();$('#pipeline-view').hidden=false;$('#opportunity-feed').hidden=true;$('#pipeline-tab').classList.add('selected');$('#all-rfps-tab').classList.remove('selected');loadRFPs();}
function showAllOpportunities(){++openingRFP;rfpDetail.back();$('#pipeline-view').hidden=true;$('#opportunity-feed').hidden=false;$('#pipeline-tab').classList.remove('selected');$('#all-rfps-tab').classList.add('selected');opportunityFeed.load();}
$('#all-rfps-tab').onclick=showAllOpportunities;
$('#pipeline-tab').onclick=showPipeline;
function renderRFPs(){const q=$('#rfp-search').value.toLowerCase(),status=$('#rfp-status-filter').value;const rows=rfpRows.filter(r=>(!status||r.status===status)&&(!q||[r.title,r.agency,r.notes].join(' ').toLowerCase().includes(q)));rows.sort((a,b)=>{const av=a[rfpSort],bv=b[rfpSort];if(rfpSort==='deadline'&&(!av||!bv))return av?-1:bv?1:0;const n=typeof av==='number'?av-bv:String(av).localeCompare(String(bv));return rfpAscending?n:-n;});$('#rfp-count').textContent=`${rows.length} of ${rfpRows.length} RFPs · Click a column to sort or an RFP to manage it.`;$('#rfp-rows').innerHTML=rows.map(r=>`<tr><td><button class="rfp-title-link" data-rfp="${r.id}">${esc(r.title)}</button></td><td>${esc(r.agency||'—')}</td><td>${r.status==='Ready for review'?`<button class="badge ready-response-link" data-rfp-response="${r.id}" aria-label="Read and edit response: ${esc(r.title)}">Ready for review ↗</button>`:`<span class="badge ${r.status==='Closed — won'?'won':r.status==='Closed — lost'?'lost':''}">${esc(r.status)}</span>`}</td><td>${esc(r.deadline||'—')}</td><td>${r.documents}</td><td>${esc(date(r.updated))}</td></tr>`).join('')||'<tr><td colspan="6">'+(rfpRows.length?'No matching RFPs. Try another search or status.':'Your pipeline is ready. Pursue an opportunity or add an RFP.')+'</td></tr>';document.querySelectorAll('[data-rfp-response]').forEach(btn=>btn.onclick=()=>openRFP(btn.dataset.rfpResponse,{},'response'));document.querySelectorAll('[data-rfp]').forEach(btn=>btn.onclick=()=>openRFP(btn.dataset.rfp));document.querySelectorAll('[data-sort]').forEach(btn=>{const active=btn.dataset.sort===rfpSort;btn.parentElement.setAttribute('aria-sort',active?(rfpAscending?'ascending':'descending'):'none');btn.textContent=({title:'RFP',agency:'Agency',status:'Status',deadline:'Due',documents:'Files',updated:'Updated'})[btn.dataset.sort]+' '+(active?(rfpAscending?'↑':'↓'):'↕');});}
$('#rfp-search').oninput=renderRFPs;$('#rfp-status-filter').onchange=renderRFPs;
document.querySelectorAll('[data-sort]').forEach(btn=>btn.onclick=()=>{if(rfpSort===btn.dataset.sort)rfpAscending=!rfpAscending;else{rfpSort=btn.dataset.sort;rfpAscending=true;}renderRFPs();});
async function openRFP(id,seed={},selectedTab='files',interaction=null){const token=++openingRFP;await loadRFPs();if(token!==openingRFP||(interaction!==null&&interaction!==navigationInteractions))return;editingRFP=id;const r=rfpRows.find(x=>x.id===id)||seed;autopilot.setRFP(r);for(const key of ['title','agency','url','deadline','notes'])$('#rfp-'+key).value=r[key]||'';$('#rfp-status').value=r.status||'Researching';$('#rfp-save-status').textContent='';$('#rfp-originals').hidden=!id;$('#rfp-pdf-url').value=/\.pdf(?:[?#]|$)/i.test(r.url||'')?r.url:'';showView('rfps');renderRFPDocuments();await rfpDetail.open(r,selectedTab);$('#view-rfps').scrollTop=0;rememberNavigation();}
$('#add-rfp').onclick=()=>openRFP(null);$('#back-rfps').onclick=()=>{++openingRFP;rfpDetail.back();loadRFPs();};
$('#rfp-form').onsubmit=async e=>{e.preventDefault();const payload={};for(const key of ['title','agency','url','status','deadline','notes'])payload[key]=$('#rfp-'+key).value.trim();const target=editingRFP, generation=openingRFP;$('#save-rfp').disabled=true;try{const r=await api('/rfps'+(target?'/'+target:''),payload);if(generation!==openingRFP)return;editingRFP=r.id;await loadRFPs();if(generation!==openingRFP)return;$('#rfp-status').value=r.status;$('#rfp-originals').hidden=false;await rfpDetail.open(r);if(generation!==openingRFP)return;rememberNavigation();$('#rfp-save-status').textContent='Saved to your workspace.';if(!$('#rfp-pdf-url').value&&/\.pdf(?:[?#]|$)/i.test(r.url))$('#rfp-pdf-url').value=r.url;renderRFPDocuments();}catch(err){toast(err.message);}finally{$('#save-rfp').disabled=false;}};
function renderRFPDocuments(){const docs=(state?.documents||[]).filter(d=>d.rfp_id===editingRFP);$('#rfp-documents').innerHTML=docs.map(d=>`<article class="document-card"><h4>${esc(d.name)}</h4><p>Saved ${esc(date(d.added))} · ${d.media_type==='text/plain'?'saved excerpts':'extracted pages'} ${d.first_page}–${d.last_page}${d.total_pages?` of ${d.total_pages}`:''}</p>${d.source_url?`<a href="${esc(d.source_url)}" target="_blank" rel="noopener">Source ↗</a>`:''}<div class="document-actions"><button data-document="${d.id}">Review extracted text</button><a href="${API}/api/documents/${d.id}/file" target="_blank" rel="noopener">View original ↗</a><a href="${API}/api/documents/${d.id}/file?download=true">Download ↓</a></div></article>`).join('')||'<p class="muted">No originals saved for this RFP yet.</p>';bindDocuments();}
async function saveRFPDocument(button,work){button.disabled=true;const label=button.textContent;button.textContent='Saving original…';try{const result=await work();await refresh();await loadRFPs();renderRFPDocuments();rfpDetail.filesChanged();toast(result.existing?'This original is already saved.':`Original saved. ${result.pages} pages extracted.`);}catch(err){toast(err.message);}finally{button.disabled=false;button.textContent=label;}}
$('#rfp-download-form').onsubmit=e=>{e.preventDefault();saveRFPDocument($('#download-rfp-pdf'),()=>api('/rfps/'+editingRFP+'/documents/download',{url:$('#rfp-pdf-url').value.trim()}));};
$('#rfp-upload-form').onsubmit=e=>{e.preventDefault();const file=$('#rfp-upload').files[0];if(!file)return;const data=new FormData();data.append('file',file);data.append('rfp_id',editingRFP);data.append('first_page',$('#rfp-first-page').value||'1');data.append('last_page',$('#rfp-last-page').value||'0');saveRFPDocument($('#upload-rfp-pdf'),()=>api('/documents',data));};
await loadRFPs();

async function restoreNavigation(){
  const saved=navigationAtLoad;
  if(!saved||!Object.hasOwn(views,saved.view)||navigationInteractions)return;
  if(saved.rfpList==='mine')showPipeline();
  if(saved.companySection)companyProfile.selectSection(saved.companySection);
  if(['discuss','work','decisions'].includes(saved.panel))selectPanel(saved.panel);
  showView(saved.view);
  if(saved.view!=='rfps'||!saved.rfp)return;
  if(saved.rfp==='new'){await openRFP(null);return;}
  if(!/^[a-f0-9]{32}$/.test(saved.rfp))return;
  const interaction=navigationInteractions;
  try{
    const rfp=rfpRows.find(r=>r.id===saved.rfp)||(await api(`/rfps/${saved.rfp}/workspace`)).rfp;
    if(interaction!==navigationInteractions)return;
    await openRFP(saved.rfp,rfp,saved.rfpTab,interaction);
  }catch(error){toast('Could not reopen that RFP. Your RFP list is still available.');}
}
await restoreNavigation();
