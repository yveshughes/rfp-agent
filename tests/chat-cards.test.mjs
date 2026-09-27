import test from 'node:test';
import assert from 'node:assert/strict';
import {renderChatOutcome} from '../site/app/chat-cards.js';
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const config={esc,resourceURL:path=>'/w/test'+path};
test('cards link to the RFP and use scoped first-page previews',()=>{
 const result=renderChatOutcome({summary:'I updated your company profile.',profile_updated:true,rfps:[{id:'a',title:'Lighting',agency:'City',reason:'Electrical work',preview_document_id:'doc',selected:true}]},config);
 assert.match(result.actions,/data-chat-rfp="a"/);assert.match(result.actions,/\/w\/test\/api\/documents\/doc\/preview/);assert.match(result.actions,/data-chat-profile/);assert.match(result.actions,/Deadline to confirm/);assert.match(result.actions,/Selected to pursue/);
});
test('missing original uses agency details without fabricated imagery; untrusted text is escaped',()=>{
 const result=renderChatOutcome({rfps:[{id:'a',title:'<script>bad</script>',agency:'A & B',reason:'" onclick="bad',preview_document_id:null}]},config);
 assert.doesNotMatch(result.actions,/<img|<script>|data-chat-profile/);assert.match(result.actions,/&lt;script&gt;/);assert.match(result.actions,/A &amp; B/);assert.match(result.actions,/Opportunity details/);
});
