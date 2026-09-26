import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
os.environ.setdefault('BILLY_DATA_DIR', tempfile.mkdtemp(prefix='billy-opportunity-test-'))
from app import server
from app.opportunities import Page, rank, canonical

URL='https://berkeleyca.gov/doing-business/working-city/bid-proposal-opportunities'

def listing(name='Environmental review',slug='environmental',extra=''):
    return f'<main><table><tr><th>Name</th><th>Due</th></tr><tr><td><a href="{URL}/{slug}">{name}</a></td><td>10/16/2026</td></tr></table>{extra}</main>'

class OpportunityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with server.db() as c:
            for table in ('opportunity_sources','opportunity_reviews','source_scans','discovered_rfps','rfps','company_facts','watches'):
                c.execute('DELETE FROM '+table)
        server.b.busy=False;server.b.controller='billy';server.b.pending=None
        self.source={'id':5426,'name':'Berkeley','procurement_url':URL}

    def test_berkeley_all_rows_and_pagination_excludes_navigation(self):
        html='<nav><a href="'+URL+'/navigation">Nav</a></nav>'+listing(extra='<a rel="next" href="?page=1">Next</a>')
        items,following,known=Page(html,URL).listings()
        self.assertTrue(known);self.assertEqual(len(items),1)
        self.assertEqual(items[0]['deadline'],'2026-10-16')
        self.assertEqual(following,[URL+'?page=1'])
        self.assertEqual(canonical(URL+'/#fragment'),URL)

    def test_no_profile_no_score_and_low_match_retained(self):
        self.assertIsNone(rank('Environmental review','CEQA',{},True)['score'])
        facts={'experience.services':{'value':'Environmental review CEQA NEPA groundwater'}}
        good=rank('Environmental review','CEQA groundwater',facts,True)
        poor=rank('Office furniture','desks chairs',facts,True)
        self.assertGreater(good['score'],poor['score'])
        self.assertEqual(poor['score'],0)
        self.assertIn('ceqa',good['matches'])
        self.assertIsNone(rank('Environmental review','CEQA',facts,False)['score'])

    async def test_watch_membership_dedup_and_pursuit(self):
        item={'title':'Office furniture','url':'https://example.com/rfp','excerpt':'desks','text':'desks'}
        rid=server.persist_opportunity(self.source,item)
        self.assertEqual(server.persist_opportunity(self.source,item),rid)
        self.assertEqual((await server.opportunity_feed())['rows'],[])
        with server.db() as c:
            c.execute('INSERT INTO watches VALUES (?,?)',(5426,1))
            c.execute('INSERT INTO company_facts VALUES (?,?,?,?,?,?)',('experience.services','Environmental CEQA consulting','Reported by you',None,None,1))
        feed=await server.opportunity_feed()
        self.assertEqual(len(feed['rows']),1);self.assertEqual(feed['rows'][0]['fit']['score'],0)
        self.assertEqual((await server.rfps())['rows'],[])
        with server.db() as c: c.execute('UPDATE discovered_rfps SET pursued=1 WHERE rfp_id=?',(rid,))
        self.assertEqual((await server.rfps())['rows'][0]['id'],rid)
        with server.db() as c: c.execute('DELETE FROM watches')
        self.assertEqual((await server.opportunity_feed())['rows'],[])
        self.assertEqual(server.require_rfp(rid)['title'],'Office furniture')

    async def test_detail_pdf_matches_existing_pipeline_record(self):
        now=1
        with server.db() as c: c.execute('INSERT INTO rfps VALUES (?,?,?,?,?,?,?,?,?)',('existing','Existing title','Berkeley','https://example.com/original.pdf','Drafting','','Keep my notes',now,now))
        item={'title':'New source title','url':'https://example.com/detail','excerpt':'x','text':'body','attachments':[{'url':'https://example.com/original.pdf'}]}
        self.assertEqual(server.persist_opportunity(self.source,item),'existing')
        saved=server.require_rfp('existing');self.assertEqual(saved['status'],'Drafting');self.assertEqual(saved['notes'],'Keep my notes')
        self.assertEqual(len((await server.rfps())['rows']),1)

    async def test_scan_all_pages_and_detail_failure_keeps_candidates(self):
        # Patch the injected downloader by registering an isolated router with a fake reader.
        from fastapi import FastAPI
        from app.opportunities import register_opportunities
        async def fetch(url):
            if url==URL: return listing(extra='<a rel="next" href="?page=1">Next</a>').encode(),url
            if url==URL+'?page=1': return listing('Office supplies','supplies').encode(),url
            if url.endswith('/environmental'): return b'<main>CEQA NEPA environmental documentation</main>',url
            raise ValueError('Portal registration required')
        _,_,_,scan=register_opportunities(FastAPI(),server.db,[self.source],server.b,fetch,AsyncMock(),server.event)
        await scan(self.source)
        with server.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM rfps').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM opportunity_reviews WHERE reviewed IS NULL').fetchone()[0],1)
            result=c.execute('SELECT * FROM source_scans').fetchone()
            self.assertEqual(result['pages'],2);self.assertEqual(result['status'],'Partial')
        async def fail(url): raise ValueError('HTTP 403')
        _,_,_,scan=register_opportunities(FastAPI(),server.db,[self.source],server.b,fail,AsyncMock(),server.event)
        await scan(self.source)
        with server.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM rfps').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT status FROM source_scans').fetchone()[0],'Blocked')

    async def test_refresh_respects_pending_decision(self):
        server.b.pending={'id':'decision'}
        try:
            with self.assertRaises(server.HTTPException): await server.refresh_opportunities()
        finally: server.b.pending=None

    async def test_failed_later_listing_page_keeps_prior_candidates(self):
        from fastapi import FastAPI
        from app.opportunities import register_opportunities
        async def fetch(url):
            if url==URL: return listing(extra='<a rel="next" href="?page=1">Next</a>').encode(),url
            if '?page=1' in url: raise ValueError('HTTP 403')
            return b'<main>Environmental review</main>',url
        _,_,_,scan=register_opportunities(FastAPI(),server.db,[self.source],server.b,fetch,AsyncMock(),server.event)
        await scan(self.source)
        with server.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM rfps').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT status FROM source_scans').fetchone()[0],'Partial')

    async def test_refresh_retains_mapping_and_updates_unpursued_deadline(self):
        item={'title':'Environmental review','url':URL+'/environmental','excerpt':'CEQA','text':'CEQA','deadline':'2026-10-16'}
        rid=server.persist_opportunity(self.source,item)
        item['deadline']='2026-11-16';server.persist_opportunity(self.source,item)
        self.assertEqual(server.require_rfp(rid)['deadline'],'2026-11-16')
        with server.db() as c: c.execute('UPDATE rfps SET url=? WHERE id=?',('https://example.com/original.pdf',rid))
        failed=dict(item,error='HTTP 403')
        self.assertEqual(server.persist_opportunity(self.source,failed),rid)
        with server.db() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM rfps').fetchone()[0],1)

    async def test_pdf_refresh_failure_preserves_previous_review(self):
        from fastapi import FastAPI
        from app.opportunities import register_opportunities
        item={'title':'Environmental review','url':URL+'/environmental','excerpt':'Old listing','text':'NEPA groundwater original PDF evidence'}
        rid=server.persist_opportunity(self.source,item)
        async def fetch(url):
            if url==URL: return listing().encode(),url
            if url.endswith('/environmental'): return b'<main>Short description<a href="/original.pdf">RFP original</a></main>',url
            raise ValueError('PDF unavailable')
        _,_,_,scan=register_opportunities(FastAPI(),server.db,[self.source],server.b,fetch,AsyncMock(),server.event)
        await scan(self.source)
        with server.db() as c:
            review=c.execute('SELECT * FROM opportunity_reviews WHERE rfp_id=?',(rid,)).fetchone()
            self.assertEqual(review['body'],'NEPA groundwater original PDF evidence')
            self.assertIn('PDF unavailable',review['error'])

    async def test_research_rechecks_claim_after_dns_yields(self):
        async def claimed(url): server.b.busy=True
        try:
            with patch.object(server,'public_url',claimed):
                with self.assertRaises(server.HTTPException): await server.research(server.ResearchRequest(source_id=5426))
        finally: server.b.busy=False
