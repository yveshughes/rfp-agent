import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

os.environ['BILLY_DATA_DIR'] = tempfile.mkdtemp(prefix='billy-test-')
from app import server

class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_states_with_search_pagination_and_watched_filter(self):
        records=[dict(id=900001+i,name=name,state_code=code,official_url='https://example.com')
                 for i,(name,code) in enumerate([('City A','CA'),('City B','NV'),('City C','OR'),('County D','NV')])]
        with patch.object(server,'SOURCES',records):
            with server.db() as c:
                c.execute('INSERT INTO watches(source_id,added) VALUES (?,?)',(900002,0))
            try:
                combined=await server.sources(state=' ca, NV,CA ')
                self.assertEqual(combined['total'],3)
                self.assertEqual([r['id'] for r in combined['rows']],[900001,900002,900004])
                page=await server.sources(state='CA,NV',offset=1,limit=1)
                self.assertEqual(page['total'],3)
                self.assertEqual([r['id'] for r in page['rows']],[900002])
                search=await server.sources(state='CA,NV',q='City')
                self.assertEqual([r['id'] for r in search['rows']],[900001,900002])
                watched=await server.sources(state='CA,NV',watched=True)
                self.assertEqual([r['id'] for r in watched['rows']],[900002])
                self.assertEqual((await server.sources(state=''))['total'],4)
                self.assertEqual((await server.sources(state='CA'))['total'],1)
            finally:
                with server.db() as c:c.execute('DELETE FROM watches WHERE source_id=?',(900002,))

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

    async def test_rfp_lifecycle_original_and_download(self):
        import io, hashlib
        from pypdf import PdfWriter
        writer=PdfWriter()
        writer.add_blank_page(width=100,height=100)
        writer.add_blank_page(width=100,height=100)
        buf=io.BytesIO();writer.write(buf);raw=buf.getvalue()
        r=await server.create_rfp(server.RFPInput(title='Environmental review',agency='Example city',deadline='2026-10-16'))
        saved=await server.store_pdf(raw,'original.pdf',1,1,r['id'])
        doc=await server.get_document(saved['id'])
        self.assertEqual(doc['rfp_id'],r['id'])
        self.assertEqual(doc['total_pages'],2)
        self.assertEqual(len(doc['pages']),1)
        self.assertEqual((server.DATA / (doc['id']+'.pdf')).read_bytes(),raw)
        self.assertEqual(doc['sha256'],hashlib.sha256(raw).hexdigest())
        duplicate=await server.store_pdf(raw,'same-file.pdf',1,1,r['id'])
        self.assertEqual(saved['id'],duplicate['id'])
        await server.update_rfp(r['id'],server.RFPInput(title=r['title'],status='Closed — won'))
        self.assertEqual(server.require_rfp(r['id'])['status'],'Closed — won')
        row=next(x for x in (await server.rfps())['rows'] if x['id']==r['id'])
        self.assertEqual(row['documents'],1)
        full=await server.store_pdf(raw,'original.pdf',1,0,r['id'])
        self.assertNotEqual(full['id'],saved['id'])
        self.assertEqual(full['pages'],2)
        download=await server.original_document(doc['id'],True)
        self.assertIn('attachment',download.headers['content-disposition'])
        inline=await server.original_document(doc['id'],False)
        self.assertIn('inline',inline.headers['content-disposition'])

    async def test_bad_rfp_or_document_is_not_saved(self):
        for req in [server.RFPInput(title='  '),server.RFPInput(title='Test',status='Made up'),server.RFPInput(title='Test',deadline='2026-02-30')]:
            with self.assertRaises(server.HTTPException): await server.create_rfp(req)
        with self.assertRaises(server.HTTPException): await server.store_pdf(b'<html>Access denied</html>','no.pdf')
        with self.assertRaises(server.HTTPException): await server.store_pdf(b'%PDF','no.pdf',rfp_id='missing')
        with self.assertRaises(server.HTTPException): await server.fetch_pdf('http://127.0.0.1/private.pdf')

    async def test_pdf_redirect_cannot_reach_private_service(self):
        async def addresses(url):
            if '127.0.0.1' in url: raise server.HTTPException(400,'Private')
            return ['93.184.216.34']
        with patch.object(server,'public_addresses',addresses),patch.object(server,'fetch_pinned',return_value=(None,'http://127.0.0.1/private.pdf')) as fetch:
            with self.assertRaises(server.HTTPException): await server.fetch_pdf('https://example.org/original.pdf')
        fetch.assert_called_once_with('https://example.org/original.pdf','93.184.216.34')

    async def test_pdf_fetch_connects_to_vetted_ip_not_hostname(self):
        from unittest.mock import MagicMock
        conn=MagicMock(); conn.getresponse.return_value.status=200
        conn.getresponse.return_value.getheader.return_value='0'
        conn.getresponse.return_value.read.return_value=b'%PDF-test'
        with patch.object(server.http.client,'HTTPConnection',return_value=conn),patch.object(server.socket,'create_connection') as connect:
            server.fetch_pinned('http://public.example/original.pdf','93.184.216.34')
        connect.assert_called_once_with(('93.184.216.34',80),timeout=15)
        self.assertEqual(conn.request.call_args.kwargs['headers']['Host'],'public.example')

    async def test_watch_allowance_and_filter_persist(self):
        records=[{'id':i,'name':f'City {i}','state_code':'CA','official_url':'https://example.org'} for i in range(3)]
        with patch.object(server,'SOURCES',records),patch.object(server,'WATCH_LIMIT',2):
            await server.watch_source(0,server.WatchRequest(watched=True))
            await server.watch_source(0,server.WatchRequest(watched=True))
            await server.watch_source(1,server.WatchRequest(watched=True))
            with self.assertRaises(server.HTTPException) as error:
                await server.watch_source(2,server.WatchRequest(watched=True))
            self.assertEqual(error.exception.status_code,409)
            result=await server.sources(watched=True)
            self.assertEqual(result['watch_count'],2)
            self.assertEqual({r['id'] for r in result['rows']},{0,1})
            await server.watch_source(0,server.WatchRequest(watched=False))
            await server.watch_source(2,server.WatchRequest(watched=True))
            with server.db() as c:
                self.assertEqual({r['source_id'] for r in c.execute('SELECT source_id FROM watches')},{1,2})
                c.execute('DELETE FROM watches')

    async def test_document_activity_tracks_overlapping_jobs_and_cleans_up(self):
        self.assertEqual(server.document_jobs,0)
        with self.assertRaises(RuntimeError):
            async with server.document_work():
                self.assertEqual((await server.state())['document_jobs'],1)
                async with server.document_work():
                    self.assertEqual(server.document_jobs,2)
                self.assertEqual(server.document_jobs,1)
                raise RuntimeError('PDF processing failed')
        self.assertEqual((await server.state())['document_jobs'],0)

if __name__=='__main__': unittest.main()
