import os
import tempfile
import unittest
os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-company-test-'))
from app import server
from app.company import ProfileAnswer, ProfileEvidence, ProfileTaskUpdate

class CompanyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with server.db() as c:
            for table in ['company_facts','company_messages','company_dialogue','company_tasks']:
                c.execute('DELETE FROM '+table)

    async def answer(self,text,field='insurance.coverage',action='answer'):
        return await server.company_chat(ProfileAnswer(field=field,text=text,action=action))

    async def test_no_research_requires_acceptance_and_persists(self):
        await self.answer('example',action='insurance_example')
        result=await self.answer('No')
        self.assertEqual(result['profile']['facts']['insurance.coverage']['status'],'Gap reported')
        self.assertEqual(result['profile']['tasks'],[])
        await self.answer('Maybe later')
        self.assertEqual((await server.company_profile())['tasks'],[])
        result=await self.answer('Yes')
        self.assertEqual(result['profile']['tasks'][0]['kind'],'research')
        self.assertEqual(result['profile']['tasks'][0]['status'],'Queued')
        self.assertEqual(result['profile']['facts']['insurance.coverage']['value'],'No')
        # Follow-ups deduplicate while queued, even in a later conversation.
        await self.answer('No');await self.answer('Yes')
        tasks=(await server.company_profile())['tasks']
        self.assertEqual(len(tasks),1)
        await server.company_task(tasks[0]['id'],ProfileTaskUpdate(status='Done'))
        self.assertEqual((await server.company_profile())['tasks'][0]['status'],'Done')
        self.assertEqual((await server.company_profile())['facts']['insurance.coverage']['status'],'Gap reported')

    async def test_freeform_negative_and_uncertain_answers(self):
        result=await self.answer('No, we don’t have coverage')
        self.assertEqual(result['profile']['facts']['insurance.coverage']['status'],'Gap reported')
        self.assertEqual(result['profile']['tasks'],[])
        await self.answer('Not now')
        result=await self.answer("I'm not sure whether we have $5M")
        self.assertEqual(result['profile']['facts']['insurance.coverage']['status'],'Unknown')
        self.assertEqual(result['profile']['tasks'][0]['kind'],'verify')

    async def test_yes_and_unsure_never_verify(self):
        for text,status in [('Yes','Reported by you'),('Not sure','Unknown')]:
            result=await self.answer(text)
            self.assertEqual(result['profile']['facts']['insurance.coverage']['status'],status)
            self.assertEqual(result['profile']['tasks'][0]['kind'],'verify')
        self.assertEqual(len(result['profile']['tasks']),1)
        self.assertIn('verification task',result['reply'])

    async def test_evidence_validates_page_and_correction_invalidates_evidence(self):
        import io
        from pypdf import PdfWriter
        writer=PdfWriter();writer.add_blank_page(width=100,height=100)
        out=io.BytesIO();writer.write(out)
        doc=await server.store_pdf(out.getvalue(),'certificate.pdf')
        req=dict(field='insurance.limits',document_id=doc['id'],value='$2M per occurrence')
        with self.assertRaises(server.HTTPException):
            await server.company_evidence(ProfileEvidence(**req,page=2))
        result=await server.company_evidence(ProfileEvidence(**req,page=1))
        self.assertEqual(result['facts']['insurance.limits']['status'],'Evidence linked')
        self.assertEqual(result['facts']['insurance.limits']['document_id'],doc['id'])
        result=await self.answer('Actually $1M',field='insurance.limits')
        self.assertEqual(result['profile']['facts']['insurance.limits']['status'],'Reported by you')
        self.assertIsNone(result['profile']['facts']['insurance.limits']['document_id'])
        with self.assertRaises(server.HTTPException):
            await server.company_evidence(ProfileEvidence(**{**req,'document_id':'missing'},page=1))

    async def test_field_conversations_are_scoped_and_do_not_infer_unknowns(self):
        await self.answer('No')
        await self.answer('Example Agency',field='company.legal_name')
        result=await self.answer('Not now')
        self.assertEqual(result['profile']['facts']['company.legal_name']['value'],'Example Agency')
        self.assertEqual(result['profile']['facts']['insurance.coverage']['value'],'No')
        self.assertEqual(result['profile']['tasks'],[])
        with self.assertRaises(server.HTTPException):await self.answer('x',field='bad')
        with self.assertRaises(server.HTTPException):await self.answer('   ')

if __name__=='__main__':unittest.main()
