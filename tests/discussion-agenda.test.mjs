import test from 'node:test';
import assert from 'node:assert/strict';
import {renderAgenda} from '../site/app/discussion-agenda.js';
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
test('agenda presents selectable questions with overflow and escaped labels',()=>{
 const html=renderAgenda({items:Array.from({length:7},(_,i)=>({label:i?'Current insurance':'<script>',status:'Not added'}))},esc);
 assert.match(html,/7 open topics/);assert.match(html,/2 more topics/);assert.match(html,/data-agenda-topic="6"/);assert.doesNotMatch(html,/<script>/);assert.doesNotMatch(html,/checkbox/);
});
test('empty agenda has no invented followup',()=>{assert.match(renderAgenda({items:[]},esc),/Nothing waiting to discuss/);});
