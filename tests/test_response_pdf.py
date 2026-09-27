import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from fastapi import FastAPI
from pypdf import PdfReader
from app.response_pdf import register_response_pdf,render_response


class ResponsePDFTests(unittest.IsolatedAsyncioTestCase):
    async def test_immutable_export_and_stale_version(self):
        with tempfile.TemporaryDirectory() as folder:
            app=FastAPI()
            def db():
                c=sqlite3.connect(Path(folder)/'test.sqlite3');c.row_factory=sqlite3.Row;return c
            with db() as c:
                c.execute('CREATE TABLE rfps(id TEXT PRIMARY KEY,status TEXT,updated REAL)')
                c.execute("INSERT INTO rfps VALUES ('pdf-test','Drafting',0)")
            sections=[{'id':str(i),'title':'Section '+str(i),'body':'Evidence <quoted> & reviewed. [CONFIRM CURRENT RATES]','version':1} for i in range(1,4)]
            rfp={'title':'Review test'}
            async def workspace(_):return {'rfp':rfp,'sections':sections}
            export=register_response_pdf(app,db,Path(folder),workspace,lambda *args:None)
            first=await export('pdf-test')
            with db() as c:self.assertEqual(c.execute("SELECT status FROM rfps WHERE id='pdf-test'").fetchone()[0],'Ready for review')
            self.assertEqual(first,await export('pdf-test'))
            original=(Path(folder)/'response-pdfs'/(first['id']+'.pdf')).read_bytes()
            extracted=''.join(p.extract_text() for p in PdfReader(io.BytesIO(original)).pages)
            self.assertIn('Evidence <quoted> & reviewed.',extracted)
            self.assertIn('REVIEW COPY',extracted)
            sections[0]['body']='Revised evidence';sections[0]['version']=2
            second=await export('pdf-test')
            self.assertNotEqual(first['id'],second['id'])
            self.assertEqual(original,(Path(folder)/'response-pdfs'/(first['id']+'.pdf')).read_bytes())
            listing=next(r.endpoint for r in app.routes if r.path=='/api/response-pdfs')
            rows=await listing()
            self.assertTrue(next(r for r in rows if r['id']==first['id'])['stale'])
            self.assertFalse(next(r for r in rows if r['id']==second['id'])['stale'])
            rfp['title']='Renamed opportunity'
            renamed=await export('pdf-test')
            self.assertNotEqual(second['id'],renamed['id'])
            rows=await listing()
            self.assertTrue(next(r for r in rows if r['id']==second['id'])['stale'])
            self.assertFalse(next(r for r in rows if r['id']==renamed['id'])['stale'])
            sections[1]['body']=''
            with self.assertRaises(ValueError):await export('pdf-test')

    def test_long_sections_paginate_without_losing_end_text(self):
        raw,count=render_response('Review',[{'title':'Long section','body':'Original evidence. '*1800+'END OF EVIDENCE'}])
        pages=PdfReader(io.BytesIO(raw)).pages
        self.assertGreater(count,1)
        self.assertIn('END OF EVIDENCE',' '.join(pages[-1].extract_text().split()))

    def test_unsupported_names_fail_instead_of_becoming_boxes(self):
        with self.assertRaisesRegex(ValueError,'Keep original names intact'):
            render_response('Review',[{'title':'Team','body':'Project lead: Łukasz; partner: 東京株式会社.'}])
