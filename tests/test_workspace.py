import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

os.environ['BILLY_DATA_DIR'] = tempfile.mkdtemp(prefix='billy-test-')
from app import server

class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(server.SOURCE_FILE.exists(), "Private source dataset required")
    async def test_directory_and_jurisdiction(self):
        all_rows = await server.sources(q='',state='',offset=0,limit=100)
        self.assertEqual(all_rows['total'],6222)
        ca = await server.sources(q='',state='CA',offset=0,limit=100)
        self.assertEqual(ca['total'],272)
        berkeley = await server.sources(q='Berkeley',state='CA',offset=0,limit=30)
        self.assertEqual([r['id'] for r in berkeley['rows']],[5426])
        last = await server.sources(q='',state='',offset=6200,limit=100)
        self.assertEqual(len(last['rows']),22)

    async def test_private_and_credential_urls_rejected(self):
        for url in ['http://localhost/','http://127.0.0.1/','http://169.254.169.254/','http://[::1]/','file:///etc/passwd','https://user:secret@example.com/','https://example.com:8787/']:
            with self.subTest(url=url), self.assertRaises(server.HTTPException):
                await server.public_url(url)

    async def test_dns_private_resolution_rejected(self):
        with patch.object(asyncio.get_running_loop(),'getaddrinfo',AsyncMock(return_value=[(2,1,6,'',('10.1.1.1',443))])):
            with self.assertRaises(server.HTTPException): await server.public_url('https://public-looking.example/')

    async def test_control_prevents_agent_navigation(self):
        server.b.controller='you'
        try:
            with self.assertRaises(server.HTTPException) as e:
                await server.research(server.ResearchRequest(source_id=5426))
            self.assertEqual(e.exception.status_code,409)
        finally: server.b.controller='billy'

    async def test_approval_is_explicit_one_use_and_expires(self):
        server.b.pending={'id':'test','kind':'submission','method':'POST','url':'https://example.com/submit'}
        with patch.object(server,'public_url',AsyncMock(return_value='https://example.com/submit')):
            with self.assertRaises(server.HTTPException):
                await server.approval(server.Approval(id='stale',approved=True))
            self.assertIsNone(server.b.allowed_write)
            await server.approval(server.Approval(id='test',approved=True))
        self.assertIsNone(server.b.pending)
        self.assertEqual(server.b.allowed_write[:2],('POST','https://example.com/submit'))
        self.assertGreater(server.b.allowed_write[2],server.time.time())
        request=type('Request',(),{'url':'https://example.com/submit','method':'POST'})()
        route=type('Route',(),{'request':request,'continue_':AsyncMock(),'abort':AsyncMock()})()
        with patch.object(server,'public_url',AsyncMock(return_value=request.url)):
            await server.b.route(route)
            route.continue_.assert_awaited_once()
            self.assertIsNone(server.b.allowed_write)
            await server.b.route(route)
            route.abort.assert_awaited_once()

    async def test_form_decline_does_not_resume_submission(self):
        page = type('Page',(),{'evaluate':AsyncMock()})()
        previous = server.b.page
        server.b.page = page
        try:
            await server.b.form_approval(None,{'url':'https://example.com/form','method':'GET'})
            pending_id = server.b.pending['id']
            self.assertEqual(server.b.pending['kind'],'form')
            page.evaluate.assert_not_awaited()
            await server.approval(server.Approval(id=pending_id,approved=False))
            self.assertIsNone(server.b.pending)
            self.assertIn('__billyResumeForm = null',page.evaluate.call_args.args[0])
        finally:
            server.b.page=previous

    async def test_saving_research_preserves_source_and_timestamp(self):
        record={'url':'https://example.com/rfp','checked':12345,'text':'Source evidence'}
        server.save('research',record)
        self.assertEqual(server.read('research'),record)

if __name__=='__main__': unittest.main()
