import os,tempfile,unittest
os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-import-test-'))
from fastapi import HTTPException
from pydantic import ValidationError
from app import server
from app.opportunity_imports import OpportunityImport,ImportVisibility

class ImportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):self.clean()
    def tearDown(self):self.clean()
    def clean(self):
        with server.db() as c:
            for t in ('opportunity_catalog_links','opportunity_sources','opportunity_reviews','discovered_rfps','rfps','watches'):
                c.execute('DELETE FROM '+t)
        with server.catalog_db() as c:
            c.execute('DELETE FROM catalog_items');c.execute('DELETE FROM catalog_batches')
    def request(self):
        return OpportunityImport(label='Jev California test',rows=[dict(title='Electrical upgrades',url='https://example.com/electrical',agencies=['Agency'],description='Upgrade electrical panels and switchgear.',status='open',description_quality='listing_description')])
    async def test_remove_restore_preserves_pursued_rfp_and_user_work(self):
        result=await server.import_opportunities(self.request())
        rows=(await server.opportunity_feed())['rows'];self.assertEqual(len(rows),1)
        row=rows[0];self.assertIsNone(row['reviewed']);self.assertEqual(row['imported']['status'],'open')
        self.assertEqual((await server.rfps())['rows'],[])
        with server.db() as c:
            c.execute('UPDATE discovered_rfps SET pursued=1 WHERE rfp_id=?',(row['id'],))
            c.execute("UPDATE rfps SET notes='My saved notes',status='Drafting' WHERE id=?",(row['id'],))
        await server.import_visibility(result['id'],ImportVisibility(active=False))
        self.assertEqual((await server.opportunity_feed())['rows'],[])
        saved=(await server.rfps())['rows'];self.assertEqual(len(saved),1);self.assertEqual(saved[0]['notes'],'My saved notes')
        await server.import_visibility(result['id'],ImportVisibility(active=True))
        self.assertEqual((await server.opportunity_feed())['rows'][0]['id'],row['id'])
        self.assertEqual(server.require_rfp(row['id'])['status'],'Drafting')
    async def test_duplicates_leave_existing_data_untouched_and_retry_is_idempotent(self):
        with server.db() as c:c.execute('INSERT INTO rfps VALUES (?,?,?,?,?,?,?,?,?)',('mine','My title','My agency','https://example.com/electrical/','Drafting','','Private notes',1,1))
        request=self.request();result=await server.import_opportunities(request)
        self.assertEqual(result['skipped'],0);self.assertEqual(result['imported'],1)
        self.assertEqual((await server.opportunity_feed())['rows'][0]['id'],'mine')
        self.assertEqual(server.require_rfp('mine')['notes'],'Private notes')
        again=await server.import_opportunities(request);self.assertTrue(again['existing']);self.assertEqual(again['id'],result['id'])
        await server.import_visibility(result['id'],ImportVisibility(active=False))
        self.assertEqual((await server.rfps())['rows'][0]['id'],'mine')
    async def test_removed_batch_is_not_reintroduced_by_watch(self):
        result=await server.import_opportunities(self.request());row=(await server.opportunity_feed())['rows'][0]
        with server.db() as c:
            c.execute('INSERT INTO watches VALUES (42,1)')
            c.execute('INSERT INTO opportunity_sources VALUES (?,?,?,?)',(row['id'],42,row['url'],1))
        await server.import_visibility(result['id'],ImportVisibility(active=False))
        self.assertEqual((await server.opportunity_feed())['rows'],[])
    async def test_shared_catalog_relevance_and_work_are_separate(self):
        from fastapi import FastAPI
        from app.opportunity_imports import register_imports
        from app.opportunities import register_opportunities
        from unittest.mock import AsyncMock
        import sqlite3
        result=await server.import_opportunities(self.request())
        with tempfile.TemporaryDirectory() as directory:
            def db():
                c=sqlite3.connect(directory+'/other.sqlite3');c.row_factory=sqlite3.Row;return c
            with server.db() as source,db() as target:source.backup(target)
            _,_,toggle,sync=register_imports(FastAPI(),db,server.catalog_db)
            feed,_,_,_=register_opportunities(FastAPI(),db,[],server.b,AsyncMock(),AsyncMock(),lambda *args:None,sync)
            with server.db() as c:
                c.execute('DELETE FROM company_facts')
                c.execute('INSERT INTO company_facts VALUES (?,?,?,?,?,?)',('experience.services','electrical panels switchgear','Reported by you',None,None,1))
            with db() as c:
                c.execute('DELETE FROM company_facts')
                c.execute('INSERT INTO company_facts VALUES (?,?,?,?,?,?)',('experience.services','environmental groundwater biology','Reported by you',None,None,1))
            electric=(await server.opportunity_feed())['rows'][0]
            environmental=(await feed())['rows'][0]
            self.assertNotEqual(electric['id'],environmental['id'])
            self.assertEqual(electric['url'],environmental['url'])
            self.assertGreater(electric['fit']['score'],environmental['fit']['score'])
            with db() as c:c.execute("UPDATE rfps SET notes='Only this business' WHERE id=?",(environmental['id'],))
            self.assertNotEqual(server.require_rfp(electric['id'])['notes'],'Only this business')
            await toggle(result['id'],ImportVisibility(active=False))
            self.assertEqual((await feed())['rows'],[])
            self.assertEqual((await server.opportunity_feed())['rows'],[])
            await toggle(result['id'],ImportVisibility(active=True))
            self.assertEqual((await feed())['rows'][0]['id'],environmental['id'])
        with server.db() as c:c.execute('DELETE FROM company_facts')
    def test_bad_source_link_is_rejected(self):
        with self.assertRaises(ValidationError):OpportunityImport(label='test',rows=[dict(title='Bad',url='javascript:alert(1)')])
    async def test_source_aliases_do_not_break_feed_or_overwrite_existing_rfp(self):
        with server.db() as c:
            c.execute('INSERT INTO rfps VALUES (?,?,?,?,?,?,?,?,?)',('mine','Saved title','Agency','https://example.com/file.pdf','Drafting','','My notes',1,1))
            c.execute('INSERT INTO opportunity_sources VALUES (?,?,?,?)',('mine',42,'https://example.com/detail',1))
        req=OpportunityImport(label='aliases',rows=[dict(title='Link',url=u,description='electrical panels switchgear',description_quality='listing_description') for u in ('https://example.com/file.pdf','https://example.com/detail')])
        await server.import_opportunities(req)
        rows=(await server.opportunity_feed())['rows'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['id'],'mine')
        self.assertEqual(server.require_rfp('mine')['notes'],'My notes')
        with server.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM opportunity_catalog_links').fetchone()[0],2)
    async def test_agent_can_search_and_page_large_catalog(self):
        from unittest.mock import AsyncMock,patch
        import json
        rows=[dict(id=str(i),title='Panel '+str(i),agency='Agency',url='https://example.com/'+str(i),fit={'score':50,'label':'Some overlap','matches':['panel']},sources=[],imported={'status':'closed' if i==0 else 'open','description':'electrical '+str(i)+' x'*5000,'description_quality':'listing_description'}) for i in range(70)]
        with patch.object(server.agent,'feed',AsyncMock(return_value={'rows':rows,'method':'keyword'})):
            first=await server.agent.execute('unused','opportunities',{})
            self.assertEqual(first['total'],69);self.assertTrue(first['has_more']);self.assertLess(len(json.dumps(first)),65000)
            last=await server.agent.execute('unused','opportunities',{'offset':60})
            self.assertEqual(last['rows'][-1]['id'],'69');self.assertFalse(last['has_more'])
            found=await server.agent.execute('unused','opportunities',{'query':'Panel 69'})
            self.assertEqual([r['id'] for r in found['rows']],['69'])
    async def test_inspect_existing_rfp_retains_full_catalog_evidence(self):
        with server.db() as c:c.execute('INSERT INTO rfps VALUES (?,?,?,?,?,?,?,?,?)',('mine','Existing','Agency','https://example.com/electrical','Drafting','','Private notes',1,1))
        req=self.request();req.rows[0].description='electrical '*180+'END OF FULL DESCRIPTION'
        await server.import_opportunities(req);await server.opportunity_feed()
        result=await server.agent.execute('unused','inspect_rfp',{'rfp_id':'mine'})
        self.assertTrue(result['catalog_evidence']['description'].endswith('END OF FULL DESCRIPTION'))
        self.assertEqual(result['rfp']['notes'],'Private notes')
