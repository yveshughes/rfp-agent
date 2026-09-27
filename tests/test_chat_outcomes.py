import json
import sqlite3
import unittest
from app.chat_outcomes import attach_outcomes

class ChatOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('CREATE TABLE rfps(id TEXT,title TEXT,agency TEXT,deadline TEXT); CREATE TABLE documents(id TEXT,rfp_id TEXT,added REAL);')
        self.db.execute("INSERT INTO rfps VALUES ('a','Lighting upgrade','Test City','2026-12-01')")
        self.db.execute("INSERT INTO documents VALUES ('doc-a','a',1)")
        self.addCleanup(self.db.close)
    def step(self,tool,result,at):return {'tool':tool,'arguments':'{}','result':json.dumps(result),'created':at}
    def test_receipt_is_scoped_to_turn_and_filters_failures(self):
        messages=[{'id':1,'role':'user','created':1,'request_id':'first'}, {'id':2,'role':'billy','created':5}, {'id':3,'role':'user','created':6,'request_id':'second'}, {'id':4,'role':'billy','created':9}]
        steps=[self.step('read_company_website',{'web_page_id':'page'},2), self.step('save_fact',{'field':'experience.services'},3),self.step('pursue',{'selected':'a','reason':'Lighting capabilities'},4),self.step('save_fact',{'error':'failed','field':'team.lead'},7)]
        attach_outcomes(self.db,messages,steps)
        result=messages[1]['outcome']
        self.assertEqual(result['summary'],'I reviewed your website and updated your company profile.')
        self.assertTrue(result['profile_updated'])
        self.assertEqual(result['rfps'][0]['preview_document_id'],'doc-a')
        self.assertNotIn('outcome',messages[3])
    def test_recommendations_without_pdf_and_selected_dedup(self):
        self.db.execute('DELETE FROM documents')
        messages=[{'id':1,'role':'user','created':1,'request_id':'first'},{'id':2,'role':'billy','created':7}]
        steps=[self.step('recommend',{'recommendations':[{'id':'a','reason':'Candidate'},{'id':'unknown','reason':'Missing'}]},2),self.step('pursue',{'selected':'a','reason':'Selected reason'},3),self.step('recommend',{'recommendations':[{'id':'a','reason':'Candidate again'}]},4)]
        attach_outcomes(self.db,messages,steps)
        cards=messages[1]['outcome']['rfps']
        self.assertEqual(len(cards),1);self.assertTrue(cards[0]['selected'])
        self.assertEqual(cards[0]['reason'],'Selected reason');self.assertIsNone(cards[0]['preview_document_id'])
    def test_reads_and_queued_tasks_do_not_claim_profile_updates(self):
        messages=[{'id':1,'role':'user','created':1,'request_id':'first'},{'id':2,'role':'billy','created':4}]
        attach_outcomes(self.db,messages,[self.step('company',{'profile':{}},2),self.step('queue_followup',{'status':'Queued'},3)])
        self.assertNotIn('outcome',messages[1])

    def test_resume_carries_unreported_work_and_truncated_website_is_still_read(self):
        messages=[{'id':1,'role':'user','created':1,'request_id':'first'}, {'id':2,'role':'user','created':4,'request_id':'resume'}, {'id':3,'role':'billy','created':7}]
        steps=[self.step('read_company_website',{'web_page_id':'page','truncated':True},2),self.step('save_fact',{'field':'experience.services'},3),self.step('pursue',{'selected':'a','reason':'Lighting capabilities'},5)]
        attach_outcomes(self.db,messages,steps)
        self.assertEqual(messages[-1]['outcome']['summary'],'I reviewed your website and updated your company profile.')
        self.assertEqual(messages[-1]['outcome']['rfps'][0]['id'],'a')
