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

    def test_municode_listing_retains_all_categories_and_due_dates(self):
        html='<div class="view view-id-rfps"><table><tr><th>Title</th><th>Bid/RFP Closing Date</th></tr><tr><td><a href="/meals">Meal catering</a></td><td>10/01/2026 - 4:00pm</td><td>Open - accepting bids and proposals</td></tr><tr><td><a href="/equipment">Electric equipment</a></td><td>10/07/2026 - 2:00pm</td><td>Open - accepting bids and proposals</td></tr></table></div>'
        html+='<table><tr><td><a href="/unrelated">Unrelated proposal tips</a></td><td>10/08/2026</td></tr></table>'
        items,following,known=Page(html,'https://example.com/rfps').listings()
        self.assertTrue(known);self.assertEqual(len(items),2)
        self.assertEqual(items[0]['deadline'],'2026-10-01')
        self.assertEqual(items[1]['deadline'],'2026-10-07')

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

    async def test_municode_downloads_only_listing_attachments_not_footer_map(self):
        from fastapi import FastAPI
        from app.opportunities import register_opportunities
        seen=[]
        async def fetch(url):
            seen.append(url)
            if url==URL:
                return ('<div class="view-id-rfps">'+listing().replace('</td>','<a href="/original.pdf">RFP PDF</a></td>',1)+'</div>').encode(),url
            if url.endswith('/original.pdf'): raise ValueError('Intentional fixture download failure')
            return b'<main>Environmental review</main><div class="footer"><a href="/city-map.pdf">City Map</a></div>',url
        _,_,_,scan=register_opportunities(FastAPI(),server.db,[self.source],server.b,fetch,AsyncMock(),server.event)
        await scan(self.source)
        self.assertEqual(seen,[URL,URL+'/environmental','https://berkeleyca.gov/original.pdf'])

    def test_municode_review_text_excludes_navigation_topics(self):
        html='<div>Environmental water and groundwater navigation</div><div class="bidsrfps">Open</div><div class="field-name-body"><p>Catering meals for seniors.</p></div><div>City map and environmental department</div>'
        page=Page(html,'https://example.com/rfp')
        self.assertEqual(page.text,'Open Catering meals for seniors.')

    async def test_partial_extraction_can_rank_with_visible_warning(self):
        from fastapi import FastAPI
        from app.opportunities import register_opportunities
        import json
        with server.db() as c:
            c.execute('INSERT OR REPLACE INTO documents(id,name,first_page,last_page,added,pages,total_pages) VALUES (?,?,?,?,?,?,?)',('partial-fixture','long.pdf',1,100,1,json.dumps([{'page':1,'text':'CEQA environmental review'}]),101))
        async def fetch(url):
            if url==URL: return listing().encode(),url
            if url.endswith('.pdf'): return b'%PDF-fixture',url
            return b'<main>Environmental review <a href="/long.pdf">Supporting plan</a></main>',url
        _,_,_,scan=register_opportunities(FastAPI(),server.db,[self.source],server.b,fetch,AsyncMock(return_value={'id':'partial-fixture'}),server.event)
        await scan(self.source)
        with server.db() as c:
            r=c.execute('SELECT * FROM opportunity_reviews').fetchone()
            self.assertIsNotNone(r['reviewed'])
            self.assertIn('100-page',r['error'])
            self.assertIn('CEQA',r['body'])

    async def test_partial_refresh_updates_partial_but_preserves_complete_evidence(self):
        item={'title':'Environmental review','url':URL+'/environmental','excerpt':'Listing','text':'Primary RFP v1','partial':True,'error':'100-page extraction limit'}
        rid=server.persist_opportunity(self.source,item)
        server.persist_opportunity(self.source,dict(item,text='New primary RFP v2'))
        with server.db() as c:
            r=c.execute('SELECT * FROM opportunity_reviews WHERE rfp_id=?',(rid,)).fetchone()
            self.assertEqual(r['body'],'New primary RFP v2');self.assertFalse(r['complete'])
        server.persist_opportunity(self.source,dict(item,text='Complete review v3',error='',partial=False))
        server.persist_opportunity(self.source,dict(item,text='Incomplete v4'))
        with server.db() as c:
            r=c.execute('SELECT * FROM opportunity_reviews WHERE rfp_id=?',(rid,)).fetchone()
            self.assertEqual(r['body'],'Complete review v3');self.assertTrue(r['complete'])

    def test_quality_migration_preserves_prior_success_with_later_error(self):
        import sqlite3
        from fastapi import FastAPI
        from app.opportunities import register_opportunities
        with tempfile.TemporaryDirectory() as folder:
            def db():
                c=sqlite3.connect(folder+'/old.sqlite');c.row_factory=sqlite3.Row;return c
            with db() as c:
                c.execute('CREATE TABLE opportunity_reviews(rfp_id TEXT PRIMARY KEY,body TEXT,reviewed REAL,error TEXT)')
                c.execute('INSERT INTO opportunity_reviews VALUES (?,?,?,?)',('previous','Complete prior evidence',1,'Latest download failed'))
            register_opportunities(FastAPI(),db,[],server.b,AsyncMock(),AsyncMock(),lambda *args:None)
            with db() as c: self.assertEqual(c.execute('SELECT complete FROM opportunity_reviews').fetchone()[0],1)
