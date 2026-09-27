import io
import os
import tempfile
import time
import unittest
import uuid
os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-company-test-'))
from pypdf import PdfWriter
from app import server
from app.company import ProfileEdit, ProfileEvidence, ProfileTaskUpdate

class CompanyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with server.db() as c:
            for table in ['company_facts','company_messages','company_tasks']:
                c.execute('DELETE FROM '+table)

    async def edit(self,field,value):
        return await server.company_edit(field,ProfileEdit(value=value))

    async def test_direct_edit_saves_clears_and_records_history(self):
        result=await self.edit('company.legal_name','  Example Agency ')
        fact=result['facts']['company.legal_name']
        self.assertEqual((fact['value'],fact['status']),('Example Agency','Reported by you'))
        self.assertEqual([m['text'] for m in result['messages'] if m['field']=='company.legal_name'],['Direct edit: Example Agency'])
        result=await self.edit('company.legal_name','')
        self.assertNotIn('company.legal_name',result['facts'])
        self.assertEqual(result['messages'][-1]['text'],'Cleared this company detail.')
        with self.assertRaises(server.HTTPException):await self.edit('made.up','x')

    async def test_evidence_validates_page_and_a_correction_drops_the_link(self):
        writer=PdfWriter();writer.add_blank_page(width=100,height=100)
        out=io.BytesIO();writer.write(out)
        doc=await server.store_pdf(out.getvalue(),'certificate.pdf')
        req=dict(field='insurance.limits',document_id=doc['id'],value='$2M per occurrence')
        with self.assertRaises(server.HTTPException):
            await server.company_evidence(ProfileEvidence(**req,page=2))
        result=await server.company_evidence(ProfileEvidence(**req,page=1))
        self.assertEqual(result['facts']['insurance.limits']['status'],'Evidence linked')
        self.assertEqual(result['facts']['insurance.limits']['document_id'],doc['id'])
        # Re-saving the same text keeps the evidence; a different statement never inherits it.
        result=await self.edit('insurance.limits','$2M per occurrence')
        self.assertEqual(result['facts']['insurance.limits']['document_id'],doc['id'])
        result=await self.edit('insurance.limits','Actually $1M')
        self.assertEqual(result['facts']['insurance.limits']['status'],'Reported by you')
        self.assertIsNone(result['facts']['insurance.limits']['document_id'])
        with self.assertRaises(server.HTTPException):
            await server.company_evidence(ProfileEvidence(**{**req,'document_id':'missing'},page=1))

    async def test_follow_up_status_changes_and_queue_uniqueness(self):
        first,second=uuid.uuid4().hex,uuid.uuid4().hex
        with server.db() as c:
            c.execute('INSERT INTO company_tasks VALUES (?,?,?,?,?,?)',(first,'insurance.coverage','research','Research liability options','Queued',time.time()))
            c.execute('INSERT INTO company_tasks VALUES (?,?,?,?,?,?)',(second,'insurance.coverage','research','Older research task','Done',time.time()))
        with self.assertRaises(server.HTTPException):
            await server.company_task(second,ProfileTaskUpdate(status='Queued'))
        result=await server.company_task(first,ProfileTaskUpdate(status='Done'))
        self.assertEqual({t['id']:t['status'] for t in result['tasks']},{first:'Done',second:'Done'})
        result=await server.company_task(second,ProfileTaskUpdate(status='Queued'))
        self.assertEqual(next(t for t in result['tasks'] if t['id']==second)['status'],'Queued')
        self.assertEqual(result['messages'][-1]['text'],'Marked follow-up queued: Older research task')
        with self.assertRaises(server.HTTPException):await server.company_task('missing',ProfileTaskUpdate(status='Done'))
        with self.assertRaises(server.HTTPException):await server.company_task(first,ProfileTaskUpdate(status='Later'))

if __name__=='__main__':unittest.main()
