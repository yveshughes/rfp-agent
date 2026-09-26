import os
import tempfile
import unittest
os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-response-test-'))
from app import server
from app.rfp_workspace import ResponseSection, ResponseCheck, ResponseNote

class ResponseTests(unittest.IsolatedAsyncioTestCase):
    async def make_rfp(self):
        return (await server.create_rfp(server.RFPInput(title='Test opportunity')))['id']

    async def test_saved_progress_and_drafts_are_scoped_to_rfp(self):
        a,b=await self.make_rfp(),await self.make_rfp()
        initial=await server.rfp_workspace(a)
        self.assertEqual(initial['progress'],0)
        self.assertEqual(len(initial['sections']),3)
        checks=[ResponseCheck(text='One',done=True),ResponseCheck(text='Two',done=False)]
        result=await server.save_response_section(a,'1',ResponseSection(title='Qualifications',body='Our approach',checks=checks))
        self.assertEqual(result['sections'][0]['progress'],50)
        self.assertEqual(result['progress'],8) # 1 of 12 total manual checks
        self.assertEqual((await server.rfp_workspace(a))['sections'][0]['body'],'Our approach')
        self.assertEqual((await server.rfp_workspace(b))['sections'][0]['body'],'')
        with self.assertRaises(server.HTTPException) as e:
            await server.save_response_section(a,'1',ResponseSection(title='Stale',checks=checks))
        self.assertEqual(e.exception.status_code,409)
        self.assertEqual((await server.rfp_workspace(a))['sections'][0]['body'],'Our approach')

    async def test_completion_requires_draft_and_valid_checklist(self):
        a=await self.make_rfp()
        with self.assertRaises(server.HTTPException):
            await server.save_response_section(a,'1',ResponseSection(title='Test',checks=[ResponseCheck(text='Reviewed',done=True)]))
        for title,checks in [(' ',[ResponseCheck(text='valid')]),('Title',[ResponseCheck(text=' ')])]:
            with self.assertRaises(server.HTTPException):await server.save_response_section(a,'1',ResponseSection(title=title,checks=checks))
        for part in ('1','2','3'):
            await server.save_response_section(a,part,ResponseSection(title='Completed section',body='Draft',checks=[ResponseCheck(text='Reviewed',done=True)]))
        self.assertEqual((await server.rfp_workspace(a))['progress'],100)
        with self.assertRaises(server.HTTPException):await server.rfp_workspace('missing')
        with self.assertRaises(server.HTTPException):await server.save_response_section(a,'4',ResponseSection(title='X',checks=[ResponseCheck(text='X')]))

    async def test_discussion_notes_are_isolated_and_do_not_change_progress(self):
        a,b=await self.make_rfp(),await self.make_rfp()
        await server.add_response_note(a,'files',ResponseNote(text='Please check the addendum.'))
        result=await server.add_response_note(a,'2',ResponseNote(text='Delivery is in six weeks.'))
        self.assertEqual([n['section_id'] for n in result['notes']],['files','2'])
        self.assertEqual(result['progress'],0)
        self.assertEqual((await server.rfp_workspace(b))['notes'],[])
        with self.assertRaises(server.HTTPException):await server.add_response_note(a,'bad',ResponseNote(text='X'))
        with self.assertRaises(server.HTTPException):await server.add_response_note(a,'1',ResponseNote(text=' '))

if __name__=='__main__':unittest.main()
