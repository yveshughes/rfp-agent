import test from 'node:test';
import assert from 'node:assert/strict';
import {completionFor,canAcceptCompletion,suggestedPrompts} from '../site/app/chat-suggestions.js';

test('completion extends matching text without replacing an unrelated draft',()=>{
  const candidates=suggestedPrompts(null);
  assert.equal(completionFor('',candidates),candidates[0]);
  assert.equal('find rfp'+completionFor('find rfp',candidates),'find rfps that match my business and help me apply.');
  assert.equal(completionFor('We carry $1M of insurance',candidates),'');
  assert.equal(completionFor('Find\nRFPs',candidates),'');
  assert.equal(completionFor(candidates[0],candidates),'');
});

test('Right Arrow accepts only at the end with no selection, modifiers or composition',()=>{
  const input={value:'Find',selectionStart:4,selectionEnd:4};
  assert.equal(canAcceptCompletion({key:'ArrowRight'},input,' RFPs'),true);
  for(const modifier of ['shiftKey','ctrlKey','altKey','metaKey','isComposing'])
    assert.equal(canAcceptCompletion({key:'ArrowRight',[modifier]:true},input,' RFPs'),false);
  assert.equal(canAcceptCompletion({key:'ArrowRight'},input,' RFPs',true),false);
  assert.equal(canAcceptCompletion({key:'ArrowRight'},{...input,selectionStart:2,selectionEnd:2},' RFPs'),false);
  assert.equal(canAcceptCompletion({key:'ArrowRight'},{...input,selectionStart:0},' RFPs'),false);
  assert.equal(canAcceptCompletion({key:'Enter'},input,' RFPs'),false);
  assert.equal(canAcceptCompletion({key:'ArrowRight'},input,''),false);
});

test('workflow suggestions reflect real state without approving submission or inventing facts',()=>{
  assert.deepEqual(suggestedPrompts({run:{status:'running'}}),[]);
  assert.match(suggestedPrompts({run:{status:'waiting',rfp_id:'a'}})[0],/still need/);
  assert.match(suggestedPrompts({run:{status:'waiting',rfp_id:'a'},pdfs:[{rfp_id:'a',stale:false}]})[0],/before I approve/);
  assert.match(suggestedPrompts({run:{status:'waiting',rfp_id:'a'},pdfs:[{rfp_id:'a',stale:true}]})[0],/still need/);
  assert.match(suggestedPrompts({run:{status:'error'}})[0],/Continue/);
});
