import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-autopilot-test-'))
from app import server
from app.agent import AgentAction,AgentTurn,AgentResume,DiscussionContext
from app.rfp_workspace import ResponseSection,ResponseCheck


class AutopilotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await server.agent.close()
        with server.db() as c:
            for table in ('agent_queue_items','agent_queues','agent_modes','agent_message_documents','agent_runs','agent_messages','agent_steps','agent_analysis','agent_usage','agent_read_pages'):
                c.execute('DELETE FROM '+table)
        env=patch.dict(os.environ,{'VULTR_SERVERLESS_INFERENCE_API_KEY':'test-only','BILLY_VULTR_MODEL':'test-model'})
        env.start();self.addCleanup(env.stop)
        async def accept(rid,messages,action):return action,'test-model',{}
        review=patch.object(server.agent,'review_completion',side_effect=accept);review.start();self.addCleanup(review.stop)
        # Pursuing an RFP opens its source in the VM browser; tests never launch Chromium.
        async def fake_research(url,source_id=None,company=False):server.b.busy=False;return {'url':url}
        browser=patch.object(server.b,'research',side_effect=fake_research);browser.start();self.addCleanup(browser.stop)
        server.b.busy=False;server.b.controller='billy';server.b.pending=None
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

    async def test_pursue_opens_the_source_in_billys_browser_when_idle(self):
        url='https://berkeleyca.gov/doing-business/working-city/bid-proposal-opportunities/environmental-review-support-and-technical'
        with patch('app.server.public_url',return_value=url):
            rfp=(await server.create_rfp(server.RFPInput(title='Browser demo',url=url)))['id']
        with server.db() as c:c.execute("INSERT INTO agent_runs VALUES ('run','running',NULL,'test',1,1,'')")
        await server.agent.execute('run','pursue',{'rfp_id':rfp,'reason':'fit'})
        await server.b.task
        server.b.research.assert_awaited_once_with(url)
        server.b.busy=True
        await server.agent.execute('run','pursue',{'rfp_id':rfp,'reason':'again'})
        self.assertEqual(server.b.research.await_count,1)   # a busy browser is never interrupted
        server.b.busy=False

    async def test_blocked_source_page_degrades_to_a_note_not_an_error(self):
        with patch('app.server.public_url',return_value='https://agency.example/blocked'):
            rfp=(await server.create_rfp(server.RFPInput(title='Blocked portal',url='https://agency.example/blocked')))['id']
        with server.db() as c:c.execute("INSERT INTO agent_runs VALUES ('run','running',NULL,'test',1,1,'')")
        async def blocked(url,source_id=None,company=False):
            server.b.error='The portal returned HTTP 403. You can inspect it or try again.';server.b.status='Needs your attention';server.b.busy=False;return None
        with patch.object(server.b,'research',side_effect=blocked):
            await server.agent.execute('run','pursue',{'rfp_id':rfp,'reason':'fit'})
            await server.b.task
        self.assertIsNone(server.b.error)
        self.assertEqual(server.b.status,'Working from the saved original')
        with server.db() as c:
            kind,title=c.execute("SELECT kind,title FROM events ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual((kind,title),('working','Source page not available to Billy’s browser'))

    async def test_autopilot_start_requests_the_browser_tour(self):
        import time
        server.tour_state.update({'requested':0.0,'cycle_done':time.time()})
        with patch('app.agent.complete',side_effect=[(AgentAction(tool='finish',arguments={'message':'Nothing suitable right now.','blocked_reason':'No candidates'}),'test-model',{})]*2):
            await server.agent.message(AgentTurn(text='Keep going',request_id='tour-start',autopilot=True,continuous=True))
            await server.agent.task
        self.assertGreater(server.tour_state['requested'],server.tour_state['cycle_done'])
        server.tour_state.update({'requested':0.0,'cycle_done':time.time()})

    async def test_queue_lists_pipeline_rfps_first(self):
        import json
        a=(await server.create_rfp(server.RFPInput(title='Catalog candidate')))['id']
        b=(await server.create_rfp(server.RFPInput(title='Already pursued',status='Researching')))['id']
        with server.db() as c:
            c.execute("INSERT INTO agent_runs VALUES ('queue-run','running',NULL,'test',1,1,'')")
            c.execute("INSERT INTO agent_queues VALUES ('queue-run','s1',1)")
            c.execute('INSERT INTO discovered_rfps VALUES (?,0)',(a,))
        with patch.object(server.agent,'feed',new=AsyncMock(return_value={'rows':[
            {'id':a,'title':'Catalog candidate','agency':'','url':'','deadline':'','pursued':0,'status':'Researching','fit':{'score':90,'label':'Strong overlap','matches':[]},'sources':[],'reviewed':1},
            {'id':b,'title':'Already pursued','agency':'','url':'','deadline':'','pursued':1,'status':'Researching','fit':{'score':40,'label':'Some overlap','matches':[]},'sources':[],'reviewed':1}],'method':''})):
            result=await server.agent.execute('queue-run','opportunities',{})
        self.assertEqual([r['title'] for r in result['rows']],['Already pursued','Catalog candidate'])
        self.assertEqual([r['in_pipeline'] for r in result['rows']],[True,False])
        self.assertTrue(result['in_pipeline_first'])

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

    async def test_continuous_queue_prepares_two_responses_without_waiting_for_review(self):
        with patch('app.server.public_url',return_value='https://agency.example/second'):
            second=(await server.create_rfp(server.RFPInput(title='Second lighting project',url='https://agency.example/second',deadline='2099-06-01')))['id']
        ids=[self.rfp,second];docs={}
        for rid in ids:
            with server.db() as c:c.execute('INSERT INTO discovered_rfps(rfp_id,pursued) VALUES (?,0)',(rid,))
            with patch.object(server.rfp_research,'fetch',return_value=(b'<main>Provide a lighting installation plan. Include team qualifications, implementation schedule and a detailed fee proposal.</main>','https://agency.example/rfp')):
                docs[rid]=(await server.rfp_research.read(rid))['document']['id']
        actions=[]
        for rid in ids:
            actions.extend([AgentAction(tool='pursue',arguments={'rfp_id':rid,'reason':'Lighting fit, with time before the deadline.'}),
                AgentAction(tool='read_document',arguments={'document_id':docs[rid]}),
                AgentAction(tool='save_analysis',arguments={'requirements':[{'text':'Lighting plan','document_id':docs[rid],'page':1,'quote':'Provide a lighting installation plan.','status':'needs_confirmation','gap_question':'Confirm schedule.'}]}),
                *[AgentAction(tool='save_section',arguments={'section_id':str(i),'title':'Section '+str(i),'body':'Lighting installation. [NEEDS CONFIRMATION: schedule]','version':0}) for i in range(1,4)],
                AgentAction(tool='export_pdf'),AgentAction(tool='finish',arguments={'message':'This is an excessively long completed response. '*20})])
        actions.append(AgentAction(tool='finish',arguments={'message':'No further suitable opportunities remain.','blocked_reason':'No further suitable opportunities remain.'}))
        iterator=iter(actions);researching=[]
        async def provider(rid,messages):
            action=next(iterator)
            if action.tool=='read_document':
                snapshot=await server.agent.snapshot()
                self.assertEqual(snapshot['run']['status'],'running')
                pipeline=(await server.rfps())['rows']
                target=next(r for r in pipeline if r['id']==snapshot['run']['rfp_id'])
                self.assertEqual(target['status'],'Researching');researching.append(target['id'])
            return action,'test-model',{}
        with patch.object(server.agent,'request_action',side_effect=provider):
            await server.agent.message(AgentTurn(text='Keep preparing suitable RFPs.',autopilot=True,continuous=True,request_id='queue-e2e'))
            await server.agent.task
        snap=await server.agent.snapshot()
        self.assertEqual(snap['run']['status'],'complete',snap['run']['error']);self.assertTrue(snap['run']['continuous'])
        self.assertEqual(researching,ids)
        self.assertEqual([(i['rfp_id'],i['status']) for i in snap['run']['queue_items']],[(rid,'ready') for rid in ids])
        self.assertEqual([m['role'] for m in snap['messages']].count('user'),1)
        for rid in ids:self.assertTrue((await server.response_review(rid))['ready'])
        with self.assertRaisesRegex(ValueError,'already handled'):
            await server.agent.execute(snap['run']['id'],'pursue',{'rfp_id':self.rfp,'reason':'Again'})
        rows=[{'id':rid,'title':'Lighting','agency':'Agency','deadline':'2099-01-01','status':'Researching','fit':{}} for rid in ids]
        with patch.object(server.agent,'feed',return_value={'rows':rows}):
            self.assertEqual((await server.agent.execute(snap['run']['id'],'opportunities',{}))['rows'],[])

    async def test_blocked_item_is_skipped_and_queue_survives_pause_resume(self):
        with patch('app.server.public_url',return_value='https://agency.example/second'):
            second=(await server.create_rfp(server.RFPInput(title='Next project',url='https://agency.example/second',deadline='2099-06-01')))['id']
        actions=iter([AgentAction(tool='pursue',arguments={'rfp_id':self.rfp,'reason':'Possible fit'}),
            AgentAction(tool='finish',arguments={'message':'Source unavailable; moving on.','blocked_reason':'Source unavailable.'}),
            AgentAction(tool='pursue',arguments={'rfp_id':second,'reason':'Next suitable fit'})])
        waiting=asyncio.Event()
        async def provider(*args):
            action=next(actions,None)
            if action:return action,'test-model',{}
            waiting.set();await asyncio.Future()
        with patch.object(server.agent,'request_action',side_effect=provider):
            await server.agent.message(AgentTurn(text='Keep going.',autopilot=True,continuous=True,request_id='queue-pause'))
            await asyncio.wait_for(waiting.wait(),2)
            snap=await server.agent.pause()
        self.assertEqual(snap['run']['status'],'paused');self.assertEqual(snap['run']['rfp_id'],second)
        self.assertEqual(snap['run']['queue_items'][0]['status'],'blocked')
        with server.db() as c:session=c.execute('SELECT session_id FROM agent_queues').fetchone()[0]
        waiting.clear()
        with patch.object(server.agent,'request_action',side_effect=provider):
            await server.agent.resume();await asyncio.wait_for(waiting.wait(),2)
            resumed=await server.agent.pause()
        self.assertEqual(resumed['run']['rfp_id'],second)
        self.assertEqual(resumed['run']['queue_items'],snap['run']['queue_items'])
        with server.db() as c:self.assertEqual(c.execute('SELECT session_id FROM agent_queues').fetchone()[0],session)

    async def test_resume_upgrades_single_run_and_keeps_completed_pdf_unchanged(self):
        for i in range(1,4):
            await server.save_response_section(self.rfp,str(i),ResponseSection(title='Section '+str(i),body='Saved response for review.',version=0,checks=[ResponseCheck(text='Review')]))
        pdf=await server.agent.export_pdf(self.rfp)
        async def wait(*args):await asyncio.Future()
        with patch.object(server.agent,'request_action',side_effect=wait):
            await server.agent.message(AgentTurn(text='Prepare this response.',autopilot=True,context=DiscussionContext(rfp_id=self.rfp),request_id='single-resume'))
            await asyncio.sleep(0);await server.agent.pause()
        action=AgentAction(tool='finish',arguments={'message':'No further suitable opportunities remain.','blocked_reason':'No further suitable opportunities remain.'})
        with patch('app.agent.complete',return_value=(action,'test-model',{})) as provider:
            await server.agent.resume(AgentResume(continuous=True));await server.agent.task
        snap=await server.agent.snapshot()
        self.assertTrue(snap['run']['continuous']);self.assertEqual(snap['run']['status'],'complete')
        self.assertEqual(snap['run']['queue_items'][0]['status'],'ready')
        self.assertEqual((await server.response_review(self.rfp))['pdf']['id'],pdf['id'])
        self.assertEqual(provider.call_count,1)

    async def test_workspace_blocker_stops_continuous_queue(self):
        action=AgentAction(tool='finish',arguments={'message':'Add company capability evidence before I can prepare responses.','blocked_reason':'No usable company evidence.','queue_stop':True})
        with patch('app.agent.complete',return_value=(action,'test-model',{})):
            await server.agent.message(AgentTurn(text='Keep going.',autopilot=True,continuous=True,context=DiscussionContext(rfp_id=self.rfp),request_id='queue-blocked'))
            await server.agent.task
        snap=await server.agent.snapshot()
        self.assertEqual(snap['run']['status'],'complete');self.assertTrue(snap['run']['blocked_reason'])
        self.assertEqual(snap['run']['queue_items'],[])

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
