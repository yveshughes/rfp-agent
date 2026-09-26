import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-agent-test-'))
from app import server
from app.agent import AgentAction,AgentTurn
from fastapi import HTTPException

class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await server.agent.close()
        with server.db() as c:
            for table in ('agent_runs','agent_messages','agent_steps','agent_analysis','agent_usage','agent_read_pages'):
                c.execute('DELETE FROM '+table)
        self.env=patch.dict(os.environ,{'VULTR_SERVERLESS_INFERENCE_API_KEY':'test-only','BILLY_VULTR_MODEL':'test-model'})
        self.env.start();self.addCleanup(self.env.stop)

    async def asyncTearDown(self):await server.agent.close()

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

    async def test_provider_failure_never_becomes_success(self):
        with patch('app.agent.complete',side_effect=RuntimeError('Model unavailable')):
            await server.agent.message(AgentTurn(text='Find RFPs',request_id='fail'))
            await server.agent.task
        snap=await server.agent.snapshot()
        self.assertEqual(snap['run']['status'],'error')
        self.assertEqual(snap['run']['error'],'Model unavailable')
        self.assertEqual(snap['steps'],[])

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

    async def test_budget_preflight_prevents_provider_call(self):
        with patch.dict(os.environ,{'BILLY_INFERENCE_BUDGET_USD':'0'}),patch('app.agent.complete') as provider:
            await server.agent.message(AgentTurn(text='Find RFPs',request_id='budget'))
            await server.agent.task
            provider.assert_not_called()
        self.assertIn('budget',(await server.agent.snapshot())['run']['error'])
