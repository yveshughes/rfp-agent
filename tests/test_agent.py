import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-agent-test-'))
from app import server
from app.agent import AgentAction,AgentTurn,InvalidAction,complete
from fastapi import HTTPException

class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await server.agent.close()
        with server.db() as c:
            for table in ('agent_message_documents','agent_runs','agent_messages','agent_steps','agent_analysis','agent_usage','agent_read_pages','company_tasks'):
                c.execute('DELETE FROM '+table)
        self.env=patch.dict(os.environ,{'VULTR_SERVERLESS_INFERENCE_API_KEY':'test-only','BILLY_VULTR_MODEL':'test-model'})
        self.env.start();self.addCleanup(self.env.stop)
        async def accept_review(rid,messages,action):return action,'test-model',{}
        self.review_patch=patch.object(server.agent,'review_completion',side_effect=accept_review)
        self.review_patch.start();self.addCleanup(self.review_patch.stop)

    async def asyncTearDown(self):await server.agent.close()

    async def test_company_attachments_persist_and_unknown_ids_are_rejected(self):
        import io
        from fastapi import UploadFile
        doc=await server.company_attachment(UploadFile(filename='services.txt',file=io.BytesIO(b'Lighting and electrical installation.')))
        action=AgentAction(tool='ask',arguments={'message':'I saved your file. Which detail should I review?'})
        with patch('app.agent.complete',return_value=(action,'test-model',{})):
            await server.agent.message(AgentTurn(text='Update our profile',document_ids=[doc['id']],request_id='attach'))
            await server.agent.task
        snap=await server.agent.snapshot()
        self.assertEqual(snap['messages'][0]['attachments'][0]['id'],doc['id'])
        self.assertEqual(snap['messages'][0]['attachments'][0]['name'],'services.txt')
        self.assertTrue(all(m['role']!='context' for m in snap['messages']))
        with server.db() as c:
            context=c.execute("SELECT text FROM agent_messages WHERE role='context'").fetchone()[0]
            self.assertIn('untrusted evidence',context)
        with self.assertRaises(HTTPException) as error:
            await server.agent.message(AgentTurn(text='Read this',document_ids=['unknown'],request_id='invalid-attach'))
        self.assertEqual(error.exception.status_code,404)

    async def test_profile_receipt_and_recommendation_cards_persist_without_pursuing(self):
        rfp=(await server.create_rfp(server.RFPInput(title='Lighting upgrade',agency='Test city')))['id']
        acts=iter([AgentAction(tool='save_fact',arguments={'field':'experience.services','value':'Lighting','quote':'We do lighting'}),AgentAction(tool='recommend',arguments={'recommendations':[{'rfp_id':rfp,'reason':'Lighting services fit the scope.'}]}),AgentAction(tool='ask',arguments={'message':'Which opportunity would you like to review?'})])
        with patch('app.agent.complete',side_effect=lambda _: (next(acts),'test-model',{})):
            await server.agent.message(AgentTurn(text='We do lighting. Recommend relevant RFPs.',request_id='cards'))
            await server.agent.task
        result=await server.agent.snapshot()
        self.assertIsNone(result['run']['rfp_id'])
        outcome=result['messages'][-1]['outcome']
        self.assertEqual(outcome['summary'],'I updated your company profile.')
        self.assertEqual(outcome['rfps'][0]['id'],rfp)
        self.assertFalse(outcome['rfps'][0]['selected'])
        self.assertEqual(outcome,(await server.agent.snapshot())['messages'][-1]['outcome'])

    async def test_real_tool_loop_persists_and_pauses_for_user(self):
        acts=iter([AgentAction(tool='company'),AgentAction(tool='opportunities'),AgentAction(tool='ask',arguments={'message':'Would you like to upload your previous response?'})])
        with patch('app.agent.complete',side_effect=lambda _: (next(acts),'test-model',{'prompt_tokens':10})):
            result=await server.agent.message(AgentTurn(text='Find RFPs and help apply',request_id='one'))
            self.assertEqual(result['run']['status'],'running')
            await server.agent.task
        snap=await server.agent.snapshot()
        self.assertEqual(snap['run']['status'],'waiting')
        self.assertEqual([s['tool'] for s in snap['steps']],['company','opportunities','ask'])
        self.assertEqual(snap['messages'][-1]['text'],'Would you like to upload your previous response?')
        self.assertEqual(snap['run']['model'],'test-model')
        duplicate=await server.agent.message(AgentTurn(text='Find RFPs and help apply',request_id='one'))
        self.assertEqual(len(duplicate['messages']),2)

    async def test_verbose_reply_is_rewritten_without_repeating_work(self):
        long=' '.join(['Detail']*100)
        actions=iter([AgentAction(tool='company'),AgentAction(tool='finish',arguments={'message':long}),AgentAction(tool='finish',arguments={'message':'Saved the company details with source links. Insurance still needs confirmation.'})])
        with patch('app.agent.complete',side_effect=lambda _: (next(actions),'test-model',{'prompt_tokens':10,'completion_tokens':5})) as provider:
            await server.agent.message(AgentTurn(text='Read my website',request_id='concise'))
            await server.agent.task
        snap=await server.agent.snapshot()
        self.assertEqual(snap['run']['status'],'complete')
        self.assertEqual(provider.call_count,3)
        self.assertEqual([s['tool'] for s in snap['steps']],['company','finish'])
        self.assertLessEqual(len(snap['messages'][-1]['text'].split()),40)
        self.assertIn('Insurance still needs confirmation',snap['messages'][-1]['text'])

    async def test_explicit_detail_request_can_receive_a_fuller_reply(self):
        detail=' '.join(['Useful detail.']*45)
        action=AgentAction(tool='finish',arguments={'message':detail,'detail_request_quote':'Give me a detailed breakdown'})
        with patch('app.agent.complete',return_value=(action,'test-model',{})) as provider:
            await server.agent.message(AgentTurn(text='Give me a detailed breakdown of the saved profile.',request_id='details'))
            await server.agent.task
        self.assertEqual(provider.call_count,1)
        self.assertEqual((await server.agent.snapshot())['messages'][-1]['text'],detail)

    async def test_unmatched_detail_quote_does_not_bypass_concise_default(self):
        actions=iter([AgentAction(tool='finish',arguments={'message':' '.join(['Detail']*70),'detail_request_quote':'Invented request'}),AgentAction(tool='finish',arguments={'message':'Your profile is updated. Do you have current insurance details?'})])
        with patch('app.agent.complete',side_effect=lambda _: (next(actions),'test-model',{})) as provider:
            await server.agent.message(AgentTurn(text='Update my profile',request_id='short-default'))
            await server.agent.task
        self.assertEqual(provider.call_count,2)
        self.assertLessEqual(len((await server.agent.snapshot())['messages'][-1]['text'].split()),40)

    async def test_provider_failure_never_becomes_success(self):
        with patch('app.agent.complete',side_effect=RuntimeError('Model unavailable')):
            await server.agent.message(AgentTurn(text='Find RFPs',request_id='fail'))
            await server.agent.task
        snap=await server.agent.snapshot()
        self.assertEqual(snap['run']['status'],'error')
        self.assertEqual(snap['run']['error'],'Model unavailable')
        self.assertEqual(snap['steps'],[])

    async def test_invalid_action_retries_once_before_executing(self):
        action=AgentAction(tool='ask',arguments={'message':'Upload a prior response?'})
        with patch('app.agent.complete',side_effect=[InvalidAction({'prompt_tokens':10,'completion_tokens':5}),(action,'test-model',{'prompt_tokens':12,'completion_tokens':6})]) as provider:
            await server.agent.message(AgentTurn(text='Find RFPs',request_id='format-retry'))
            await server.agent.task
        snap=await server.agent.snapshot()
        self.assertEqual(snap['run']['status'],'waiting')
        self.assertEqual(len(snap['steps']),1)
        self.assertEqual(provider.call_count,2)
        with server.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM agent_usage WHERE actual IS NOT NULL').fetchone()[0],2)

    async def test_repeated_invalid_action_stops_without_tools(self):
        with patch('app.agent.complete',side_effect=InvalidAction()) as provider:
            await server.agent.message(AgentTurn(text='Find RFPs',request_id='format-fail'))
            await server.agent.task
        self.assertEqual(provider.call_count,3)
        snap=await server.agent.snapshot()
        self.assertEqual(snap['run']['status'],'error')
        self.assertEqual(snap['steps'],[])

    async def test_native_tool_call_parsing_and_model_identity(self):
        from unittest.mock import MagicMock
        result={'model':'test-model','choices':[{'message':{'content':None,'tool_calls':[{'function':{'name':'billy_action','arguments':'{"tool":"company","arguments":{}}'}}]}}],'usage':{}}
        response=MagicMock()
        response.__enter__.return_value.read.side_effect=lambda _:json.dumps(result).encode()
        with patch('app.agent.urllib.request.urlopen',return_value=response):
            self.assertEqual(complete([{'role':'user','content':'Go'}])[0].tool,'company')
            result['choices'][0]['message']['tool_calls'][0]['function']['arguments']={'tool':'company','arguments':{}}
            self.assertEqual(complete([{'role':'user','content':'Go'}])[0].tool,'company')
            for invalid in [{'tool':'ask','arguments':{}},{'tool':'finish','arguments':{'message':None}},{'tool':'shell','arguments':{}},{'tool':'company','arguments':{},'unexpected':'field'}]:
                result['choices'][0]['message']['tool_calls'][0]['function']['arguments']=json.dumps(invalid)
                with self.assertRaises(InvalidAction):complete([{'role':'user','content':'Go'}])
            result['model']='unexpected-model'
            with self.assertRaisesRegex(RuntimeError,'different model'):complete([{'role':'user','content':'Go'}])

    async def test_missing_key_blocks_without_creating_run(self):
        with patch.dict(os.environ,{'VULTR_SERVERLESS_INFERENCE_API_KEY':''}):
            with self.assertRaises(HTTPException) as e:await server.agent.message(AgentTurn(text='Go',request_id='no-key'))
        self.assertEqual(e.exception.status_code,503)
        self.assertIsNone((await server.agent.snapshot())['run'])

    async def test_invalid_citation_and_requirement_scope_rejected(self):
        rid=(await server.create_rfp(server.RFPInput(title='Agent RFP')))['id']
        with server.db() as c:
            c.execute("INSERT INTO agent_runs VALUES ('run','waiting',?,'test',1,1,'')",(rid,))
            c.execute("INSERT OR REPLACE INTO documents(id,name,first_page,last_page,added,pages,rfp_id) VALUES ('citation','RFP',1,1,1,?,?)",(json.dumps([{'page':1,'text':'Provide three client references.'}]),rid))
        await server.agent.execute('run','read_document',{'document_id':'citation'})
        a={'requirements':[{'text':'Three references','document_id':'citation','page':1,'quote':'Five million insurance required','status':'missing','gap_question':'Coverage?'}]}
        with self.assertRaises(ValueError):await server.agent.execute('run','save_analysis',a)
        a['requirements'][0]['quote']='Provide three client references.'
        result=await server.agent.execute('run','save_analysis',a)
        self.assertEqual(result['saved'],1)
        with self.assertRaises(ValueError):await server.agent.execute('run','save_fact',{'field':'insurance.coverage','value':'insured','document_id':'citation','page':1,'quote':'Provide three client references.'})

    async def test_user_facts_require_actual_user_statement(self):
        with server.db() as c:
            c.execute("INSERT INTO agent_runs VALUES ('run','waiting',NULL,'test',1,1,'')")
            c.execute("INSERT INTO agent_messages(run_id,role,text,created) VALUES ('run','user','Our lead is Pat.',1)")
        with self.assertRaises(ValueError):await server.agent.execute('run','save_fact',{'field':'team.lead','value':'Sam','quote':'Our lead is Sam.'})
        result=await server.agent.execute('run','save_fact',{'field':'team.lead','value':'Pat','quote':'Our lead is Pat.'})
        self.assertIn('Reported by you',result['status'])
        self.assertIsNone(result['document_id'])

    async def test_no_delivery_or_shell_tools(self):
        for tool in ('send_email','submit','shell'):
            with self.assertRaises(ValueError):await server.agent.execute('run',tool,{})

    async def test_followup_requires_user_request_and_deduplicates(self):
        with server.db() as c:
            c.execute("INSERT INTO agent_messages(run_id,role,text,created) VALUES ('run','user','Please research coverage options.',1)")
        args={'field':'insurance.coverage','title':'Research liability coverage options','quote':'Please research coverage options.'}
        with self.assertRaises(ValueError):await server.agent.execute('run','queue_followup',{**args,'quote':'Buy a policy now.'})
        first=await server.agent.execute('run','queue_followup',args)
        again=await server.agent.execute('run','queue_followup',args)
        self.assertEqual(first['id'],again['id'])
        self.assertFalse(first['executed'])

    async def test_later_rfp_pages_block_analysis_until_read(self):
        rid=(await server.create_rfp(server.RFPInput(title='Long RFP')))['id']
        with server.db() as c:
            c.execute("INSERT INTO agent_runs VALUES ('run','waiting',?,'test',1,1,'')",(rid,))
            c.execute("INSERT OR REPLACE INTO documents(id,name,first_page,last_page,total_pages,added,pages,rfp_id) VALUES ('long-citation','RFP',1,9,9,1,?,?)",(json.dumps([{'page':i,'text':'Provide three client references.'} for i in range(1,10)]),rid))
        result=await server.agent.execute('run','inspect_rfp',{'rfp_id':rid})
        self.assertTrue(result['documents'][0]['has_more'])
        self.assertEqual(result['documents'][0]['next_page'],1)
        await server.agent.execute('run','read_document',{'document_id':'long-citation','count':8})
        with self.assertRaises(ValueError):server.agent.require_rfp_read('run',rid)
        await server.agent.execute('run','read_document',{'document_id':'long-citation','start_page':9})
        server.agent.require_rfp_read('run',rid)

    async def test_unread_prior_response_pages_block_drafting(self):
        with server.db() as c:
            c.execute("INSERT OR REPLACE INTO documents(id,name,first_page,last_page,total_pages,added,pages,rfp_id) VALUES ('prior-full','Prior response',32,40,72,1,?,NULL)",(json.dumps([{'page':i,'text':'Reference evidence.'} for i in range(32,41)]),))
        await server.agent.execute('run','read_document',{'document_id':'prior-full','start_page':32,'count':8})
        with self.assertRaisesRegex(ValueError,'starting page 40'):server.agent.require_imports_read('run')
        await server.agent.execute('run','read_document',{'document_id':'prior-full','start_page':40})
        server.agent.require_imports_read('run')

    async def test_snapshot_is_bounded_to_recent_messages_with_receipts(self):
        from app.agent import SNAPSHOT_MESSAGES
        with server.db() as c:
            c.execute("INSERT INTO agent_runs VALUES ('run','complete',NULL,'test',1,1,'')")
            for i in range(SNAPSHOT_MESSAGES+10):
                c.execute('INSERT INTO agent_messages(run_id,role,text,created) VALUES (?,?,?,?)',('run','user' if i%2==0 else 'billy',f'message {i}',float(i)))
            # A website read just before the first shown reply must still be credited to it.
            first_shown_reply=11.0
            c.execute('INSERT INTO agent_steps(run_id,tool,arguments,result,model,usage,created) VALUES (?,?,?,?,?,?,?)',('run','read_company_website','{}',json.dumps({'web_page_id':'p1'}),'test','{}',10.5))
            c.execute('INSERT INTO agent_steps(run_id,tool,arguments,result,model,usage,created) VALUES (?,?,?,?,?,?,?)',('run','company','{}','{}','test','{}',2.0))
        snap=await server.agent.snapshot()
        self.assertEqual(len(snap['messages']),SNAPSHOT_MESSAGES)
        self.assertEqual(snap['run']['total_messages'],SNAPSHOT_MESSAGES+10)
        self.assertTrue(snap['run']['messages_truncated'])
        self.assertEqual(snap['messages'][0]['text'],'message 10')
        self.assertEqual(snap['messages'][1]['outcome']['summary'],'I reviewed your website.')
        self.assertEqual([s['tool'] for s in snap['steps']],['read_company_website'])

    async def test_read_markers_expire_when_a_new_turn_starts(self):
        rid=(await server.create_rfp(server.RFPInput(title='Short RFP')))['id']
        with server.db() as c:
            c.execute("INSERT OR REPLACE INTO documents(id,name,first_page,last_page,total_pages,added,pages,rfp_id) VALUES ('short-doc','RFP',1,1,1,1,?,?)",(json.dumps([{'page':1,'text':'Provide three client references.'}]),rid))
        with patch('app.agent.complete',side_effect=[(AgentAction(tool='ask',arguments={'message':'Which response should I reuse?'}),'test-model',{})]):
            await server.agent.message(AgentTurn(text='Look at my RFP',request_id='turn-one'))
            await server.agent.task
        run=(await server.agent.snapshot())['run']['id']
        with server.db() as c:c.execute('UPDATE agent_runs SET rfp_id=? WHERE id=?',(rid,run))
        await server.agent.execute(run,'read_document',{'document_id':'short-doc'})
        server.agent.require_rfp_read(run,rid)
        with patch('app.agent.complete',side_effect=[(AgentAction(tool='ask',arguments={'message':'Still here?'}),'test-model',{})]):
            await server.agent.message(AgentTurn(text='Now analyze it',request_id='turn-two'))
            await server.agent.task
        with self.assertRaisesRegex(ValueError,'Read remaining RFP pages'):server.agent.require_rfp_read(run,rid)

    async def test_oversized_page_batch_unmarks_only_that_batch(self):
        with server.db() as c:
            c.execute("INSERT INTO agent_runs VALUES ('run','running',NULL,'test',1,1,'')")
            c.execute("INSERT OR REPLACE INTO documents(id,name,first_page,last_page,total_pages,added,pages,rfp_id) VALUES ('huge','RFP',1,3,3,1,?,NULL)",(json.dumps([{'page':1,'text':'short'},{'page':2,'text':'"'*40000},{'page':3,'text':'short'}]),))
        actions=iter([AgentAction(tool='read_document',arguments={'document_id':'huge','count':1}),AgentAction(tool='read_document',arguments={'document_id':'huge','start_page':2,'count':2}),AgentAction(tool='ask',arguments={'message':'Which pages next?'})])
        with patch('app.agent.complete',side_effect=lambda messages:(next(actions),'test-model',{})):
            await server.agent.message(AgentTurn(text='Read the huge file',request_id='huge-read'))
            await server.agent.task
        with server.db() as c:
            pages=sorted(r[0] for r in c.execute("SELECT page FROM agent_read_pages WHERE document_id='huge'"))
            results=[json.loads(r[0]) for r in c.execute("SELECT result FROM agent_steps WHERE tool='read_document' ORDER BY id")]
        self.assertEqual(pages,[1])
        self.assertIn('not counted as reviewed',results[1]['error'])

    async def test_budget_preflight_prevents_provider_call(self):
        with patch.dict(os.environ,{'BILLY_INFERENCE_BUDGET_USD':'0'}),patch('app.agent.complete') as provider:
            await server.agent.message(AgentTurn(text='Find RFPs',request_id='budget'))
            await server.agent.task
            provider.assert_not_called()
        self.assertIn('budget',(await server.agent.snapshot())['run']['error'])

class ActionCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await AgentTests.asyncSetUp(self)
        self.review_patch.stop()

    async def asyncTearDown(self):await server.agent.close()

    # The inherited tests isolate the ordinary loop. These cases exercise the
    # real completion-check path with explicit provider/executor receipts.
    async def test_completion_check_recovers_unperformed_actions(self):
        for name,args in [('save_fact',{'field':'team.lead','value':'Pat','quote':'Our lead is Pat.'}),
                          ('queue_followup',{'field':'insurance.coverage','title':'Research coverage','quote':'Research coverage'}),
                          ('save_section',{'section_id':1,'title':'Approach','body':'Revised','version':2}),
                          ('export_pdf',{}),('read_company_website',{})]:
            with self.subTest(tool=name):
                actions=iter([AgentAction(tool='finish',arguments={'message':'I can help with that.'}),
                    AgentAction(tool=name,arguments=args),
                    AgentAction(tool='finish',arguments={'message':'Done.'}),
                    AgentAction(tool='finish',arguments={'message':'Done.'})])
                with patch('app.agent.complete',side_effect=lambda _: (next(actions),'test-model',{})),patch.object(server.agent,'execute',return_value={'saved':True}) as execute:
                    await server.agent.message(AgentTurn(text='Please perform the requested change.',request_id='review-'+name))
                    await server.agent.task
                execute.assert_awaited_once_with((await server.agent.snapshot())['run']['id'],name,args)
                self.assertEqual((await server.agent.snapshot())['run']['status'],'complete')

    async def test_information_and_missing_approval_can_stop_without_action(self):
        for terminal in ('ask','finish'):
            action=AgentAction(tool=terminal,arguments={'message':'Submission is not connected. Your draft is saved.'})
            with patch('app.agent.complete',return_value=(action,'test-model',{})),patch.object(server.agent,'execute') as execute:
                await server.agent.message(AgentTurn(text='Can you submit this?',request_id='blocked-'+terminal))
                await server.agent.task
            execute.assert_not_awaited()
            self.assertEqual((await server.agent.snapshot())['run']['status'],'waiting' if terminal=='ask' else 'complete')

    async def test_successful_mutation_not_repeated_after_review(self):
        save=AgentAction(tool='export_pdf')
        finish=AgentAction(tool='finish',arguments={'message':'The PDF is ready.'})
        actions=iter([save,finish,save,finish,finish])
        with patch('app.agent.complete',side_effect=lambda _: (next(actions),'test-model',{})),patch.object(server.agent,'execute',return_value={'id':'pdf-1'}) as execute:
            await server.agent.message(AgentTurn(text='Export my PDF.',request_id='no-duplicate'))
            await server.agent.task
        execute.assert_awaited_once()
        self.assertEqual((await server.agent.snapshot())['run']['status'],'complete')

    async def test_failed_action_is_not_suppressed_as_completed(self):
        save=AgentAction(tool='save_section',arguments={'section_id':1})
        finish=AgentAction(tool='finish',arguments={'message':'Saved.'})
        actions=iter([save,finish,save,finish,finish])
        with patch('app.agent.complete',side_effect=lambda _: (next(actions),'test-model',{})),patch.object(server.agent,'execute',side_effect=[ValueError('Read current version first'),{'saved':True}]) as execute:
            await server.agent.message(AgentTurn(text='Save my edits.',request_id='recover'))
            await server.agent.task
        self.assertEqual(execute.await_count,2)
        self.assertEqual((await server.agent.snapshot())['run']['status'],'complete')

    async def test_export_after_edit_is_not_a_duplicate(self):
        export=AgentAction(tool='export_pdf')
        edit=AgentAction(tool='save_section',arguments={'section_id':1})
        finish=AgentAction(tool='finish',arguments={'message':'Updated PDF ready.'})
        actions=iter([export,edit,export,finish,finish])
        with patch('app.agent.complete',side_effect=lambda _: (next(actions),'test-model',{})),patch.object(server.agent,'execute',return_value={'saved':True}) as execute:
            await server.agent.message(AgentTurn(text='Export, edit, then export again.',request_id='reexport'))
            await server.agent.task
        self.assertEqual([c.args[1] for c in execute.await_args_list],['export_pdf','save_section','export_pdf'])

    async def test_handoff_preserves_roles_and_short_answer_evidence(self):
        from app.agent import DiscussionContext
        with server.db() as c:
            c.execute("DELETE FROM discussion_messages WHERE scope='general'")
            c.execute("INSERT INTO discussion_messages(scope,role,text,at) VALUES ('general','billy','Should I queue research into liability coverage?',1)")
        seen=[]
        actions=iter([AgentAction(tool='company'),AgentAction(tool='queue_followup',arguments={'field':'insurance.coverage','title':'Research liability options','quote':'Yes'}),AgentAction(tool='finish',arguments={'message':'Queued coverage research.'}),AgentAction(tool='finish',arguments={'message':'Queued coverage research.'})])
        def provider(messages):
            seen.append(messages.copy());return next(actions),'test-model',{}
        with patch('app.agent.complete',side_effect=provider):
            await server.agent.message(AgentTurn(text='Yes',context=DiscussionContext(),request_id='handoff'))
            await server.agent.task
        self.assertTrue(any(m['role']=='assistant' and m['content']=='Should I queue research into liability coverage?' for m in seen[0]))
        snap=await server.agent.snapshot()
        self.assertEqual(snap['run']['status'],'complete')
        self.assertEqual(snap['messages'][-2]['text'],'Yes')
        with server.db() as c:
            result=json.loads(c.execute("SELECT result FROM agent_steps WHERE tool='queue_followup'").fetchone()[0])
        self.assertEqual(result['status'],'Queued')
        with self.assertRaises(ValueError):
            await server.agent.execute(snap['run']['id'],'queue_followup',{'field':'insurance.coverage','title':'Different task','quote':'es'})

    async def test_agenda_question_is_in_agent_context_for_short_answer(self):
        from app.agent import DiscussionContext
        from app.discussion import DiscussionTurn
        from app.discussion_agenda import build_agenda
        item=next(i for i in build_agenda(server.db)['items'] if i['id']=='insurance')
        await server.discuss(DiscussionTurn(**item['context'],opening_question=item['question']))
        seen=[]
        def provider(messages):
            seen.append(messages.copy())
            return AgentAction(tool='ask',arguments={'message':'Please attach the certificate here.'}),'test-model',{}
        with patch('app.agent.complete',side_effect=provider):
            await server.agent.message(AgentTurn(text='Yes',context=DiscussionContext(**item['context']),request_id='agenda-handoff'))
            await server.agent.task
        self.assertTrue(any(m['role']=='assistant' and m['content']==item['question'] for m in seen[0]))

    async def test_invalid_completion_review_recovers_without_repeating_tools(self):
        question=AgentAction(tool='ask',arguments={'message':'What is your company website? I’ll use it to find suitable RFPs.'})
        results=[(AgentAction(tool='company'),'test-model',{}),(question,'test-model',{}),InvalidAction({'prompt_tokens':12,'completion_tokens':3}), (question,'test-model',{'prompt_tokens':15,'completion_tokens':5})]
        with patch('app.agent.complete',side_effect=results) as provider:
            await server.agent.message(AgentTurn(text='Find RFPs that match my business and help me apply.',request_id='review-retry'))
            await server.agent.task
        snap=await server.agent.snapshot()
        self.assertEqual(snap['run']['status'],'waiting')
        self.assertEqual([s['tool'] for s in snap['steps']],['company','ask'])
        self.assertEqual(provider.call_count,4)
        self.assertIn('company website',snap['messages'][-1]['text'])
        with server.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM agent_usage WHERE actual IS NOT NULL').fetchone()[0],2)

    async def test_review_repeated_invalid_output_stays_bounded(self):
        question=AgentAction(tool='ask',arguments={'message':'What is your website?'})
        with patch('app.agent.complete',side_effect=[(question,'test-model',{}),InvalidAction(),InvalidAction(),InvalidAction()]) as provider,patch.object(server.agent,'execute') as execute:
            await server.agent.message(AgentTurn(text='Find matches.',request_id='review-exhausted'))
            await server.agent.task
        self.assertEqual(provider.call_count,4)
        execute.assert_not_awaited()
        self.assertEqual((await server.agent.snapshot())['run']['status'],'error')
