import json,sqlite3,unittest
from app.document_review import current_document_review

class DocumentReviewTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE documents(id TEXT,name TEXT,media_type TEXT,first_page INTEGER,last_page INTEGER,total_pages INTEGER,pages TEXT)')
        for id in ['a','b']:self.c.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)',(id,id+'.pdf','application/pdf',1,3,3,json.dumps([{'page':p,'text':'evidence'} for p in [1,2,3]])))
        self.messages=[{'role':'user','created':10,'attachments':[{'id':'a'}]}]
    def step(self,doc,pages,time=11):return {'tool':'read_document','created':time,'result':json.dumps({'id':doc,'pages':[{'page':p,'text':'private text'} for p in pages]})}
    def test_actual_reads_choose_document_deduplicate_progress_and_omit_text(self):
        view=current_document_review(self.c,self.messages,[self.step('a',[1,2]),self.step('a',[2,3])])
        self.assertEqual(view['reviewed_pages'],3);self.assertEqual(view['extracted_pages'],3);self.assertNotIn('pages',view)
        view=current_document_review(self.c,self.messages,[self.step('a',[1]),self.step('b',[2])]);self.assertEqual(view['id'],'b');self.assertEqual(view['reviewed_pages'],1)
    def test_unread_attachment_is_not_claimed_read_and_prior_turn_is_excluded(self):
        view=current_document_review(self.c,self.messages,[self.step('a',[1,2,3],9)])
        self.assertEqual(view['reviewed_pages'],0)
        self.messages.append({'role':'user','created':15,'attachments':[]})
        self.assertIsNone(current_document_review(self.c,self.messages,[self.step('a',[1])]))
    def test_failed_read_and_missing_workspace_document(self):
        step={'tool':'read_document','created':11,'result':json.dumps({'error':'Too large'})}
        self.assertEqual(current_document_review(self.c,self.messages,[step])['reviewed_pages'],0)
        self.c.execute('DELETE FROM documents');self.assertIsNone(current_document_review(self.c,self.messages,[self.step('a',[1])]))
