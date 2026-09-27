import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-autopilot-test-'))
from app import server
from app.agent import AgentAction,AgentTurn,DiscussionContext
from app.rfp_workspace import ResponseSection,ResponseCheck


class AutopilotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await server.agent.close()
        with server.db() as c:
            for table in ('agent_modes','agent_message_documents','agent_runs','agent_messages','agent_steps','agent_analysis','agent_usage','agent_read_pages'):
                c.execute('DELETE FROM '+table)
        env=patch.dict(os.environ,{'VULTR_SERVERLESS_INFERENCE_API_KEY':'test-only','BILLY_VULTR_MODEL':'test-model'})
        env.start();self.addCleanup(env.stop)
        async def accept(rid,messages,action):return action,'test-model',{}
        review=patch.object(server.agent,'review_completion',side_effect=accept);review.start();self.addCleanup(review.stop)
        with patch('app.server.public_url',return_value='https://agency.example/rfp'):
            self.rfp=(await server.create_rfp(server.RFPInput(title='Lighting renewal',url='https://agency.example/rfp',deadline='2099-05-01')))['id']

    async def asyncTearDown(self):await server.agent.close()

    async def test_autopilot_continues_past_permission_question_and_builds_review_pdf(self):
        html=b'<main><h1>Lighting renewal RFP</h1><p>Provide a lighting installation plan. Closing date: May 1, 2099. Include qualifications and fees.</p></main>'
        with patch.object(server.rfp_research,'fetch',return_value=(html,'https://agency.example/rfp')):
            source=await server.rfp_research.read(self.rfp)
        doc=source['document']['id']
        actions=[AgentAction(tool='ask',arguments={'message':'May I draft your response?'}),
            AgentAction(tool='read_document',arguments={'document_id':doc}),
            AgentAction(tool='save_analysis',arguments={'requirements':[{'text':'Lighting plan','document_id':doc,'page':1,'quote':'Provide a lighting installation plan.','status':'needs_confirmation','gap_question':'Confirm the site schedule.'}]}),
            *[AgentAction(tool='save_section',arguments={'section_id':str(i),'title':'Section '+str(i),'body':'Lighting installation response. [NEEDS CONFIRMATION: site schedule]','version':0}) for i in range(1,4)],
            AgentAction(tool='export_pdf'),AgentAction(tool='finish',arguments={'message':'Your response is ready for review, with the site schedule flagged for confirmation.'})]
        iterator=iter(actions);seen=[]
        def provider(messages):seen.append(messages.copy());return next(iterator),'test-model',{}
        with patch('app.agent.complete',side_effect=provider):
            await server.agent.message(AgentTurn(text='Prepare this with Autopilot.',autopilot=True,context=DiscussionContext(rfp_id=self.rfp),request_id='autopilot-e2e'))
            await server.agent.task
        snap=await server.agent.snapshot();self.assertEqual(snap['run']['status'],'complete',snap['run']['error'])
        self.assertTrue(snap['run']['autopilot']);self.assertNotIn('May I draft',snap['messages'][-1]['text'])
        self.assertIn('AUTOPILOT IS ENABLED',seen[0][0]['content'])
        self.assertIn('days remaining',seen[0][0]['content'])
        review=await server.response_review(self.rfp)
        self.assertTrue(review['ready']);self.assertFalse(review['submission_connected'])
        self.assertEqual(review['rfp']['status'],'Ready for review');self.assertEqual(len(review['gaps']),1)
        self.assertTrue(all(not c['done'] for s in review['sections'] for c in s['checks']))
        changed=review['sections'][0]
        await server.save_response_section(self.rfp,'1',ResponseSection(title=changed['title'],body='Edited draft',version=changed['version'],checks=[ResponseCheck(text='Review')]))
        review=await server.response_review(self.rfp)
        self.assertFalse(review['ready']);self.assertIsNone(review['pdf']);self.assertEqual(review['rfp']['status'],'Drafting')

    async def test_real_blocker_is_reported_without_claiming_ready(self):
        action=AgentAction(tool='finish',arguments={'message':'The agency source is unavailable, so I couldn’t prepare a response.','blocked_reason':'The original requirements could not be retrieved.'})
        with patch('app.agent.complete',return_value=(action,'test-model',{})):
            await server.agent.message(AgentTurn(text='Find one match.',autopilot=True,request_id='blocked'))
            await server.agent.task
        snap=await server.agent.snapshot()
        self.assertTrue(snap['run']['blocked_reason']);self.assertIsNone(snap['run']['rfp_id'])

    async def test_autopilot_cannot_start_expired_target(self):
        with server.db() as c:c.execute("UPDATE rfps SET deadline='2000-01-01' WHERE id=?",(self.rfp,))
        with self.assertRaises(server.HTTPException) as exc:
            await server.agent.message(AgentTurn(text='Prepare',autopilot=True,context=DiscussionContext(rfp_id=self.rfp),request_id='expired'))
        self.assertEqual(exc.exception.status_code,409)

    async def test_targeted_preparation_adds_opportunity_to_my_rfps(self):
        with server.db() as c:c.execute('INSERT INTO discovered_rfps(rfp_id,pursued) VALUES (?,0)',(self.rfp,))
        action=AgentAction(tool='finish',arguments={'message':'Source needs attention.','blocked_reason':'Source unavailable.'})
        with patch('app.agent.complete',return_value=(action,'test-model',{})):
            await server.agent.message(AgentTurn(text='Prepare this',autopilot=True,context=DiscussionContext(rfp_id=self.rfp),request_id='targeted'))
            await server.agent.task
        self.assertIn(self.rfp,[r['id'] for r in (await server.rfps())['rows']])

    async def test_newly_discovered_expired_deadline_blocks_drafting(self):
        async def wait(*args):await asyncio.Future()
        with patch.object(server.agent,'request_action',side_effect=wait):
            snap=await server.agent.message(AgentTurn(text='Prepare',autopilot=True,context=DiscussionContext(rfp_id=self.rfp),request_id='date-discovered'))
            await asyncio.sleep(0)
            with server.db() as c:c.execute("UPDATE rfps SET deadline='2000-01-01' WHERE id=?",(self.rfp,))
            with self.assertRaisesRegex(ValueError,'expired'):
                await server.agent.execute(snap['run']['id'],'save_section',{})
            await server.agent.pause()

    async def test_pause_and_resume_preserve_autopilot_and_selected_rfp(self):
        async def wait(*args):await asyncio.Future()
        with patch.object(server.agent,'request_action',side_effect=wait):
            await server.agent.message(AgentTurn(text='Prepare',autopilot=True,context=DiscussionContext(rfp_id=self.rfp),request_id='pause'))
            await asyncio.sleep(0)
            snap=await server.agent.pause();self.assertEqual(snap['run']['status'],'paused')
        with patch('app.agent.complete',return_value=(AgentAction(tool='finish',arguments={'message':'The original source needs attention.','blocked_reason':'Source unavailable.'}),'test-model',{})):
            await server.agent.resume();await server.agent.task
        snap=await server.agent.snapshot()
        self.assertTrue(snap['run']['autopilot']);self.assertEqual(snap['run']['rfp_id'],self.rfp)

    async def test_actionable_search_excludes_expired_and_exposes_days_remaining(self):
        rows=[{'id':str(i),'title':'Lighting','agency':'Agency','url':'https://agency.example','deadline':deadline,'status':'Researching','fit':{},'sources':[]} for i,deadline in enumerate(['2000-01-01','2099-05-01',''])]
        with patch.object(server.agent,'feed',return_value={'rows':rows}):
            result=await server.agent.execute('test','opportunities',{})
        self.assertEqual([r['id'] for r in result['rows']],['1','2'])
        self.assertGreater(result['rows'][0]['days_remaining'],0);self.assertIsNone(result['rows'][1]['days_remaining'])

    async def test_source_only_follows_recorded_links_and_reuses_saved_snapshot(self):
        html=b'<main>Official request for lighting installation. Proposals must include a work plan and pricing.<a href="/original.pdf">Original RFP</a></main>'
        with patch.object(server.rfp_research,'fetch',return_value=(html,'https://agency.example/rfp')) as fetch:
            first=await server.rfp_research.read(self.rfp)
            again=await server.rfp_research.read(self.rfp)
            self.assertEqual(first['document']['id'],again['document']['id'])
            with self.assertRaises(ValueError):await server.rfp_research.read(self.rfp,'https://unrelated.example/secret')
            self.assertEqual(fetch.await_count,2)
        with patch.object(server.rfp_research,'fetch',return_value=(b'%PDF fake','https://agency.example/original.pdf')),patch.object(server.rfp_research,'store_pdf',return_value={'id':'original'}) as store:
            result=await server.rfp_research.read(self.rfp,'https://agency.example/original.pdf')
            self.assertEqual(result['document']['id'],'original');self.assertEqual(store.call_args.kwargs['rfp_id'],self.rfp)
