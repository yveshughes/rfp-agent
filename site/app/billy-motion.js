export const motions = {
  idle: {name:'Idle', description:'Relaxed and ready for the next task.'},
  researching: {name:'Researching', description:'Scanning a source and working at the keyboard.'},
  reading: {name:'Reading', description:'Reviewing the pages of a document.'},
  waiting: {name:'Needs you', description:'Hands off the keyboard, waiting for your input.'},
};

// Visual state follows work, never a timer pretending to perform a task.
export function resolveBillyMotion(state, {connected=true, documentRequests=0}={}) {
  if (!connected || !state) return {motion:'idle',label:'Workspace disconnected',tone:'offline'};
  const browser=state.browser || {};
  if(browser.pending) return {motion:'waiting',label:'Waiting for your decision',tone:'attention'};
  if(browser.controller==='you') return {motion:'waiting',label:'You have the browser',tone:'handoff'};
  if(documentRequests>0 || state.document_jobs>0) return {motion:'reading',label:'Reading and saving a document',tone:'working'};
  if(browser.busy) return {motion:'researching',label:browser.status || 'Researching a source',tone:'working'};
  if(browser.error) return {motion:'waiting',label:'Needs your attention',tone:'attention'};
  return {motion:'idle',label:'Ready for the next task',tone:'ready'};
}

export function createBillyMotion() {
  const video=document.querySelector('#billy-video');
  const profile=document.querySelector('.billy-profile');
  const button=document.querySelector('#billy-motion');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let preference;
  try {preference=localStorage.getItem('billy-motion');} catch {}
  let enabled=preference ? preference==='on' : !reduced.matches;
  let current=null, tone='offline';
  const sync=()=>{
    const playing=enabled && !document.hidden && tone!=='offline';
    if(playing) video.play().catch(()=>{}); else video.pause();
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
      document.querySelector('#billy-state-label').textContent=motions[resolved.motion].name;
      document.querySelector('#status-dot').className='status-dot'+(tone!=='offline'?' connected':'')+(tone==='working'?' working':'');
      if(current!==resolved.motion){
        current=resolved.motion;
        delete profile.dataset.mediaError;
        video.poster=`/assets/billy/${current}.jpg`;
        video.setAttribute('aria-label',`Billy: ${motions[current].name.toLowerCase()}`);
        video.src=`/assets/billy/${current}.mp4`;
        video.load();
      }
      sync();
    }
  };
}

export function setupMotionPreview() {
  const dialog=document.querySelector('#billy-preview-dialog');
  const video=document.querySelector('#billy-preview-video');
  function select(name){
    document.querySelectorAll('[data-motion-preview]').forEach(btn=>btn.setAttribute('aria-pressed',String(btn.dataset.motionPreview===name)));
    document.querySelector('#billy-preview-description').textContent=motions[name].description;
    video.poster=`/assets/billy/${name}.jpg`;
    video.src=`/assets/billy/${name}.mp4`;
    video.load();
    if(!matchMedia('(prefers-reduced-motion: reduce)').matches)video.play().catch(()=>{});
  }
  document.querySelector('#preview-billy').onclick=()=>{dialog.showModal();select('idle');};
  document.querySelector('#close-billy-preview').onclick=()=>dialog.close();
  document.querySelectorAll('[data-motion-preview]').forEach(btn=>btn.onclick=()=>select(btn.dataset.motionPreview));
  dialog.addEventListener('close',()=>{video.pause();video.removeAttribute('src');video.load();});
}
