import test from 'node:test';
import assert from 'node:assert/strict';
import {attachmentError,renderChatAttachments} from '../site/app/chat-attachments.js';
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
test('attachment formats and message limits',()=>{
  for(const name of ['file.PDF','photo.jpeg','company.docx','notes.txt','data.csv','notes.md','image.webp'])assert.equal(attachmentError({name,size:10},0,0),'');
  assert.match(attachmentError({name:'script.html',size:10},0,0),/Choose/);
  assert.match(attachmentError({name:'file.pdf',size:26*1024*1024},0,0),/25 MB/);
  assert.match(attachmentError({name:'file.pdf',size:10},5,0),/5 files/);
  assert.match(attachmentError({name:'file.pdf',size:10},0,50*1024*1024),/50 MB/);
});
test('saved attachments have scoped links and escaped filenames',()=>{
  const html=renderChatAttachments([{id:'abc',name:'<img onerror="bad">.png',media_type:'image/png'}],{esc,resourceURL:p=>'/w/test'+p});
  assert.match(html,/\/w\/test\/api\/documents\/abc\/preview/);
  assert.match(html,/data-chat-document="abc"/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img onerror/);
  assert.equal(renderChatAttachments([],{esc,resourceURL:p=>p}),'');
});
test('partial uploads retry only unsaved files and keep staging locked',async()=>{
  const {createChatAttachments}=await import('../site/app/chat-attachments.js');
  const nodes=Object.fromEntries(['#chat-form','#chat-files','#chat-attach','#chat-attachments'].map(k=>[k,{addEventListener(){},querySelectorAll(){return [];},classList:{add(){},remove(){}},files:[]} ]));
  const oldDocument=globalThis.document;globalThis.document={querySelector:s=>nodes[s]};
  try{
    let calls=[],failed=false;
    const manager=createChatAttachments({esc,toast:()=>{},onSaved:async()=>{},api:async(path,body)=>{const name=body.get('file').name;calls.push(name);if(name==='two.txt'&&!failed){failed=true;throw Error('Network interrupted');}return {id:name};}});
    nodes['#chat-files'].files=[new File(['one'],'one.txt'),new File(['two'],'two.txt')];nodes['#chat-files'].onchange();
    await assert.rejects(manager.upload(),/Network interrupted/);assert.equal(manager.hasFiles(),true);assert.equal(manager.isBusy(),true);
    manager.setBusy(false);assert.deepEqual(await manager.upload(),['one.txt','two.txt']);assert.deepEqual(calls,['one.txt','two.txt','two.txt']);
    manager.clear();manager.setBusy(false);assert.equal(manager.hasFiles(),false);
  }finally{globalThis.document=oldDocument;}
});
