import test from 'node:test';
import assert from 'node:assert/strict';
import {reviewPresentation} from '../site/app/document-review.js';
const snapshot={run:{status:'running'},document_review:{id:'a',media_type:'application/pdf',reviewed_pages:8,extracted_pages:41,reviewed_at:100}};
test('review thumbnail uses actual evidence progress and returns browser for live browsing',()=>{
 const view=reviewPresentation(snapshot,{browser:{}},'reading');
 assert.equal(view.title,'Reviewing document');assert.equal(view.progress,'8 of 41 extracted pages reviewed');assert.match(view.caption,/First-page/);
 for(const browser of [{busy:true},{controller:'you'},{pending:{id:'approval'}}])assert.equal(reviewPresentation(snapshot,{browser},'reading'),null);
 assert.equal(reviewPresentation(snapshot,{browser:{}},'researching'),null);
 assert.equal(reviewPresentation({run:{status:'running'}},{browser:{}},'reading'),null);
});
test('completed and unread documents get accurate labels',()=>{
 assert.equal(reviewPresentation({...snapshot,run:{status:'waiting'}},{browser:{}},null).title,'Last document reviewed');
 assert.equal(reviewPresentation({...snapshot,document_review:{...snapshot.document_review,reviewed_pages:0}},{browser:{}},'reading').progress,'Preparing to review');
});

test('newer source research takes over and an existing browser stays accessible',()=>{
 assert.equal(reviewPresentation(snapshot,{browser:{ready:true},research:{checked:101}},null),null);
 assert.equal(reviewPresentation(snapshot,{browser:{ready:true},research:{checked:99}},null).browserReady,true);
});
