import asyncio
import io
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx
from pypdf import PdfWriter
os.environ['BILLY_DATA_DIR'] = tempfile.mkdtemp(prefix='billy-companies-test-')
from app import server


class CompanyWorkspacesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = server.workspace_directory
        self.lifespan = self.directory.app.router.lifespan_context(self.directory.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.directory.app), base_url='http://localhost', headers={'X-Billy-Client':'workspace'})

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)

    async def create(self, name):
        result = await self.client.post('/api/workspaces', json={'name':name})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()['id']

    async def test_company_data_files_browser_and_inflight_jobs_are_separate(self):
        a, b = await self.create('Company A'), await self.create('Company B')
        async def get(w, path):
            response = await self.client.get('/w/'+w+'/api'+path)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()
        for w, name in [(a,'Company A'),(b,'Company B')]:
            profile = await get(w, '/company')
            self.assertEqual(profile['facts']['company.legal_name']['value'],name)
            self.assertEqual((await get(w, '/agent'))['messages'],[])
        ra, rb = self.directory.runtimes[a], self.directory.runtimes[b]
        self.assertIsNot(ra.b, rb.b)
        self.assertIs(ra.SOURCES, rb.SOURCES)
        self.assertNotEqual(ra.DATA, rb.DATA)
        rfp = await ra.create_rfp(ra.RFPInput(title='Only company A'))
        writer=PdfWriter();writer.add_blank_page(width=100,height=100)
        buf=io.BytesIO();writer.write(buf)
        doc=await ra.store_pdf(buf.getvalue(),'A-only.pdf',rfp_id=rfp['id'])
        self.assertEqual(len((await get(a,'/rfps'))['rows']),1)
        self.assertEqual((await get(b,'/rfps'))['rows'],[])
        for path in ['/documents/'+doc['id'], '/documents/'+doc['id']+'/pdf', '/rfps/'+rfp['id']+'/workspace']:
            response=await self.client.get('/w/'+b+'/api'+path)
            self.assertEqual(response.status_code,404,response.text)
        pdf=await self.client.get('/w/'+a+'/api/documents/'+doc['id']+'/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.assertEqual(pdf.headers['cache-control'],'no-store')
        ready=asyncio.Event()
        async def delayed():
            await ready.wait(); ra.save('research',{'company':'A'})
        task=asyncio.create_task(delayed())
        await get(b,'/state')  # A different tab can select B while A's job is running.
        ready.set();await task
        self.assertEqual(ra.read('research'),{'company':'A'})
        self.assertIsNone(rb.read('research'))
        ra.b.pending={'id':'A-only-decision'}
        self.assertIsNone(rb.b.pending)
        with ra.db() as c:
            c.execute("INSERT INTO agent_messages(run_id,role,text,created) VALUES ('test','user','A private chat',1)")
        with rb.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM agent_messages').fetchone()[0],0)

    async def test_budget_is_shared_and_new_companies_do_not_reset_it(self):
        a, b = await self.create('Budget A'), await self.create('Budget B')
        await self.directory.runtime(a);await self.directory.runtime(b)
        ra, rb = self.directory.runtimes[a], self.directory.runtimes[b]
        with server.db() as c:
            before=c.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM agent_usage').fetchone()[0]
        with patch.dict('os.environ',{'BILLY_INFERENCE_BUDGET_USD':str(before+.021)}):
            usage_id=ra.agent.reserve_usage('A-run',[])
            with self.assertRaisesRegex(RuntimeError,'budget'):
                rb.agent.reserve_usage('B-run',[])
        ra.agent.record_usage(usage_id,{'prompt_tokens':100,'completion_tokens':100})
        with server.db() as c:
            self.assertAlmostEqual(c.execute('SELECT actual FROM agent_usage WHERE id=?',(usage_id,)).fetchone()[0],.000375)
            c.execute('DELETE FROM agent_usage WHERE id=?',(usage_id,))

    async def test_unknown_workspace_and_unsafe_origins_rejected(self):
        response=await self.client.get('/w/does-not-exist/api/state')
        self.assertEqual(response.status_code,404)
        response=await self.client.post('/api/workspaces',json={'name':'  '})
        self.assertEqual(response.status_code,400)
        response=await self.client.post('/api/workspaces',json={'name':'X'},headers={'Origin':'https://evil.example'})
        self.assertEqual(response.status_code,403)
        self.assertEqual((await self.client.get('/w/default/api/state')).status_code,200)
        self.assertEqual((await self.client.get('/api/state')).status_code,200)
        response=await self.client.options('/api/workspaces',headers={'Origin':'http://localhost:8080'})
        self.assertEqual(response.headers['access-control-allow-origin'],'http://localhost:8080')
