export const attachmentAccept='.pdf,.png,.jpg,.jpeg,.webp,.docx,.txt,.csv,.md';
export function attachmentError(file,count,total){
  if(count>=5)return 'Attach up to 5 files per message.';
  if(!attachmentAccept.split(',').includes('.'+file.name.split('.').pop().toLowerCase()))return 'Choose a PDF, image (PNG, JPG or WebP), DOCX, TXT, CSV or Markdown file.';
  if(!file.size)return 'This file is empty.';
  if(file.size>25*1024*1024)return 'Each attachment must be 25 MB or smaller.';
  if(total+file.size>50*1024*1024)return 'Keep the total attachments below 50 MB per message.';
  return '';
}
export function createChatAttachments({api,esc,toast,onSaved}){
  const form=document.querySelector('#chat-form'),input=document.querySelector('#chat-files'),button=document.querySelector('#chat-attach'),host=document.querySelector('#chat-attachments');
  let items=[],busy=false;
  const render=()=>{
    host.hidden=!items.length;
    host.innerHTML=items.map((item,i)=>`<div class="chat-attachment-chip">${item.url?`<img src="${item.url}" alt="">`:'<span aria-hidden="true">▤</span>'}<span><strong>${esc(item.file.name)}</strong><small>${item.document?'Saved to company documents':busy?'Uploading…':'Company Profile · ready to send'}</small></span><button type="button" data-remove-attachment="${i}" aria-label="Remove ${esc(item.file.name)}" ${busy?'disabled':''}>×</button></div>`).join('');
    button.disabled=busy;input.disabled=busy;
    host.querySelectorAll('[data-remove-attachment]').forEach(b=>b.onclick=()=>{const [removed]=items.splice(Number(b.dataset.removeAttachment),1);if(removed.url)URL.revokeObjectURL(removed.url);render();});
  };
  function add(files){
    if(busy)return;
    for(const file of files){
      const error=attachmentError(file,items.length,items.reduce((n,x)=>n+x.file.size,0));
      if(error){toast(error);continue;}
      if(items.some(x=>x.file.name===file.name&&x.file.size===file.size&&x.file.lastModified===file.lastModified))continue;
      items.push({file,url:/\.(png|jpe?g|webp)$/i.test(file.name)?URL.createObjectURL(file):null,document:null});
    }
    input.value='';render();
  }
  input.accept=attachmentAccept;input.onchange=()=>add(input.files);button.onclick=()=>input.click();
  form.addEventListener('dragover',event=>{if([...event.dataTransfer.types].includes('Files')){event.preventDefault();form.classList.add('attachment-drop');}});
  form.addEventListener('dragleave',()=>form.classList.remove('attachment-drop'));
  form.addEventListener('drop',event=>{if(event.dataTransfer.files.length){event.preventDefault();form.classList.remove('attachment-drop');add(event.dataTransfer.files);}});
  form.addEventListener('paste',event=>{const files=[...(event.clipboardData?.files||[])];if(files.length){event.preventDefault();add(files);}});
  return {
    setBusy(value){busy=value;render();},
    hasFiles:()=>!!items.length,
    isBusy:()=>busy,
    async upload(){
      busy=true;render();
      try{
        for(const item of items){
          if(item.document)continue;
          const data=new FormData();data.append('file',item.file);
          item.document=await api('/company/attachments',data);render();
        }
        await onSaved();return items.map(x=>x.document.id);
      }finally{render();}
    },
    clear(){for(const item of items)if(item.url)URL.revokeObjectURL(item.url);items=[];render();}
  };
}

export function renderChatAttachments(files,{esc,resourceURL}){
  return (files||[]).length?'<div class="sent-attachments">'+files.map(file=>`<button type="button" class="sent-attachment" data-chat-document="${esc(file.id)}">${(file.media_type==='application/pdf'||file.media_type?.startsWith('image/'))?`<img src="${esc(resourceURL('/api/documents/'+encodeURIComponent(file.id)+'/preview'))}" alt="Preview of ${esc(file.name)}" loading="lazy">`:'<span aria-hidden="true">▤</span>'}<span><strong>${esc(file.name)}</strong><small>Saved to Company Profile · Open ↗</small></span></button>`).join('')+'</div>':'';
}
