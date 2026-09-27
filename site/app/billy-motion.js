export const motions = {
  autopilot: {name:'Autopilot', description:'Billy works through a response at his desk, ready to bring it back for your review.'},
  voice: {name:'On the phone', description:'Billy listens, talks, and nods while holding his corded desk phone.'},
  discussing: {name:'Discussing', description:'Billy is messaging with you and keeping track of the next steps.'},
  snoozing: {name:'Snoozing', description:'A little rest between tasks. Billy wakes when there’s work to do.'},
  idle: {name:'Idle', description:'Billy’s empty desk, grayed out while he is away.'},
  researching: {name:'Researching', description:'Scanning a source and working at the keyboard.'},
  reading: {name:'Reading', description:'Reviewing the pages of a document.'},
  waiting: {name:'Needs you', description:'Billy turns toward you and waves to get your attention.'},
};

// Visual state follows work, never a timer pretending to perform a task.
export function resolveBillyMotion(state, {connected=true, documentRequests=0, discussionState=null, chatOpen=false, agentActivity=null,autopilotRunning=false}={}) {
  if (!connected || !state) return {motion:'idle',label:'Workspace disconnected',tone:'offline'};
  const browser=state.browser || {};
  if(browser.pending) return {motion:'waiting',label:'Waiting for your decision',tone:'attention'};
  if(browser.controller==='you') return {motion:'waiting',label:'You have the browser',tone:'handoff'};
  if(autopilotRunning)return {motion:'autopilot',label:agentActivity==='reading'?'Reviewing the details for your response…':'Finding the fit. Preparing your response.',tone:'working'};
  if(documentRequests>0 || state.document_jobs>0) return {motion:'reading',label:'Reading and saving a document',tone:'working'};
  if(browser.busy) return {motion:'researching',label:browser.status || 'Researching a source',tone:'working'};
  if(agentActivity) return {motion:agentActivity,label:agentActivity==='reading'?'Reviewing document evidence':'Reviewing opportunities and sources',tone:'working'};
  if(discussionState) return {motion:['listening','speaking','transcribing'].includes(discussionState)?'voice':'discussing',label:({listening:'Listening to you…',thinking:'Considering your answer…',speaking:'Talking it through…',transcribing:'Catching what you said…',ready:'Let’s work it through.'})[discussionState]||'Discussing with you',tone:'working'};
  if(browser.error) return {motion:'waiting',label:'Needs your attention',tone:'attention'};
  if(chatOpen) return {motion:'discussing',label:'Ready to talk it through with you.',tone:'working'};
  return {motion:'snoozing',label:'All quiet. Ready when you are.',tone:'resting'};
}

export function resolveAgentActivity(snapshot) {
  if(snapshot?.run?.status!=='running')return null;
  const user=snapshot.messages?.filter(m=>m.role==='user').at(-1);
  // Keep the current review visible through extraction/saving and model pauses.
  // Completed steps from earlier user turns must never wake stale activity.
  const currentSteps=(snapshot.steps||[]).filter(step=>!user||step.created>=user.created);
  for(const step of currentSteps.toReversed()){
    if(['read_document','inspect_rfp'].includes(step.tool))return 'reading';
    if(['open_source','read_rfp_source','read_company_website','opportunities'].includes(step.tool))return 'researching';
  }
  if(user?.attachments?.length)return 'reading';
  return null;
}

export function resolveBillyPanel(state, options={}) {
  const motion=resolveBillyMotion(state,options);
  if(motion.motion==='idle')return 'work';
  if(options.connected!==false && state?.browser?.pending)return 'decisions';
  if(['autopilot','reading','researching'].includes(motion.motion) || (options.connected!==false && state?.browser?.controller==='you'))return 'work';
  if(options.chatOpen || options.discussionState)return 'discuss';
  return null;
}

export function createBillyMotion() {
  const video=document.querySelector('#billy-video');
  const profile=document.querySelector('.billy-profile');
  const sleeper=document.querySelector('#billy-snooze');
  const desk=document.querySelector('#billy-idle-desk');
  const button=document.querySelector('#billy-motion');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let preference;
  try {preference=localStorage.getItem('billy-motion');} catch {}
  let enabled=preference ? preference==='on' : !reduced.matches;
  let current=null, tone='offline';
  const sync=()=>{
    const playing=enabled && !document.hidden && tone!=='offline';
    if(playing && !['idle','snoozing'].includes(current)) video.play().catch(()=>{}); else video.pause();
    button.hidden=current==='idle';
    profile.dataset.animate=playing?'running':'paused';
    button.textContent=enabled?'Ⅱ':'▷';
    button.setAttribute('aria-label',enabled?'Pause Billy animation':'Play Billy animation');
    button.setAttribute('aria-pressed',String(enabled));
    profile.dataset.motion=enabled?'on':'off';
  };
  button.onclick=()=>{enabled=!enabled;preference=enabled?'on':'off';try{localStorage.setItem('billy-motion',preference);}catch{}sync();};
  document.addEventListener('visibilitychange',sync);
  reduced.addEventListener('change',()=>{if(!preference)enabled=!reduced.matches;sync();});
  video.addEventListener('loadeddata',sync);
  video.addEventListener('error',()=>{video.pause();video.poster='/assets/agent-poster.jpg';profile.dataset.mediaError='true';});
  return {
    update(state,options){
      const resolved=resolveBillyMotion(state,options);
      tone=resolved.tone;
      profile.dataset.state=resolved.motion;
      profile.dataset.tone=tone;
      document.querySelector('#billy-status').textContent=resolved.label;
      document.querySelector('#billy-state-label').textContent=options?.autopilotRunning&&resolved.motion!=='idle'?'Autopilot':motions[resolved.motion].name;
      document.querySelector('#status-dot').className='status-dot'+(tone!=='offline'?' connected':'')+(tone==='working'?' working':'');
      if(current!==resolved.motion){
        current=resolved.motion;
        delete profile.dataset.mediaError;
        const asleep=current==='snoozing';
        const idle=current==='idle';
        desk.hidden=!idle;sleeper.hidden=!asleep;video.hidden=idle||asleep;
        if(!idle&&!asleep){
        const asset=current==='voice'?'voice-conversation':current==='waiting'?'waiting-wave':['discussing','autopilot'].includes(current)?'researching':current;
        video.poster=`/assets/billy/${asset}.jpg`;
        video.setAttribute('aria-label',`Billy: ${motions[current].name.toLowerCase()}`);
        video.src=`/assets/billy/${asset}.mp4`;
        video.load();
        }
      }
      video.playbackRate=resolved.motion==='autopilot'?1.8:1;
      sync();
      return resolved;
    }
  };
}

export function setupMotionPreview() {
  const dialog=document.querySelector('#billy-preview-dialog');
  const video=document.querySelector('#billy-preview-video');
  const stage=document.querySelector('#billy-preview-stage');
  const sleeper=document.querySelector('#billy-preview-snooze');
  const desk=document.querySelector('#billy-preview-idle-desk');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let enabled=!reduced.matches;
  const toggle=document.querySelector('#snooze-preview-motion');
  const sync=()=>{
    stage.dataset.animate=enabled&&!document.hidden?'running':'paused';
    toggle.textContent=enabled?'Pause animation':'Play animation';
    toggle.setAttribute('aria-pressed',String(enabled));
  };
  toggle.onclick=()=>{enabled=!enabled;sync();};
  document.addEventListener('visibilitychange',sync);
  function select(name){
    document.querySelectorAll('[data-motion-preview]').forEach(btn=>btn.setAttribute('aria-pressed',String(btn.dataset.motionPreview===name)));
    document.querySelector('#billy-preview-description').textContent=motions[name].description;
    const asleep=name==='snoozing',idle=name==='idle';
    stage.dataset.state=name;desk.hidden=!idle;sleeper.hidden=!asleep;video.hidden=idle||asleep;toggle.hidden=!asleep;
    sync();
    if(idle||asleep){video.pause();return;}
    const asset=name==='voice'?'voice-conversation':name==='waiting'?'waiting-wave':name==='discussing'?'researching':name;
    video.poster=`/assets/billy/${asset}.jpg`;
    video.src=`/assets/billy/${asset}.mp4`;
    video.load();
    if(!matchMedia('(prefers-reduced-motion: reduce)').matches)video.play().catch(()=>{});
  }
  document.querySelector('#preview-billy').onclick=()=>{dialog.showModal();select('snoozing');};
  document.querySelector('#close-billy-preview').onclick=()=>dialog.close();
  document.querySelectorAll('[data-motion-preview]').forEach(btn=>btn.onclick=()=>select(btn.dataset.motionPreview));
  dialog.addEventListener('close',()=>{video.pause();video.removeAttribute('src');video.load();});
}
