export function reviewPresentation(snapshot,state,activity){
  const doc=snapshot?.document_review;
  if(!doc || state?.browser?.busy || state?.browser?.pending || state?.browser?.controller==='you' || activity==='researching')return null;
  if(state?.browser?.ready && state?.research?.checked>doc.reviewed_at)return null;
  const running=snapshot.run?.status==='running';
  const reviewed=doc.reviewed_pages||0,total=doc.extracted_pages||0;
  return {doc,browserReady:!!state?.browser?.ready,title:running?'Reviewing document':reviewed?'Last document reviewed':'Attached document',
    progress:reviewed?`${reviewed} of ${total} extracted ${doc.media_type==='application/pdf'?'pages':'excerpts'} reviewed`:running?'Preparing to review':'Ready to review',
    preview:doc.media_type==='application/pdf'||doc.media_type?.startsWith('image/'),
    caption:doc.media_type==='application/pdf'?'First-page preview · Open original ↗':'Open original ↗'};
}
export function createDocumentReview({esc,resourceURL,openDocument,openBrowser}){
  const host=document.querySelector('#document-review'),browser=document.querySelector('#activity-browser');let signature='';
  return {update(snapshot,state,activity){
    const view=reviewPresentation(snapshot,state,activity);host.hidden=!view;browser.hidden=!!view;
    const key=JSON.stringify(view);if(key===signature)return;signature=key;
    if(!view){host.innerHTML='';return;}
    const {doc}=view;
    host.innerHTML=`<div class="panel-heading"><h3>${esc(view.title)}</h3></div><button class="review-document-card" type="button" aria-label="Open ${esc(doc.name)}"><div class="review-document-cover">${view.preview?`<img src="${esc(resourceURL('/api/documents/'+encodeURIComponent(doc.id)+'/preview'))}" alt="${doc.media_type==='application/pdf'?'First page of':'Preview of'} ${esc(doc.name)}">`:''}<span class="review-document-fallback" ${view.preview?'hidden':''}>▤<small>Open document to review</small></span></div><strong>${esc(doc.name)}</strong><span>${esc(view.progress)}</span><small>${esc(view.caption)}</small></button>${view.browserReady?'<button type="button" class="review-open-browser">Open Billy’s browser ↗</button>':''}`;
    host.querySelector('button').onclick=()=>openDocument(doc.id);
    const browserButton=host.querySelector('.review-open-browser');if(browserButton)browserButton.onclick=openBrowser;
    const image=host.querySelector('img');if(image)image.onerror=()=>{image.hidden=true;host.querySelector('.review-document-fallback').hidden=false;};
  }};
}
