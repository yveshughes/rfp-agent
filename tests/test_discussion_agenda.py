import sqlite3,json,unittest
from app.discussion_agenda import build_agenda,TOPICS

class AgendaTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
  self.c.executescript('CREATE TABLE company_facts(field TEXT PRIMARY KEY,value TEXT,status TEXT,document_id TEXT);CREATE TABLE company_tasks(id TEXT,title TEXT,status TEXT,field TEXT,created REAL);CREATE TABLE agent_runs(rfp_id TEXT,created REAL);CREATE TABLE agent_analysis(rfp_id TEXT,requirements TEXT);')
 def test_missing_topics_are_not_claimed_rfp_requirements(self):
  agenda=build_agenda(lambda:self.c)
  self.assertEqual(len(agenda['items']),8);self.assertEqual(agenda['covered'],0)
  self.assertTrue(all(i['status']=='Not added' for i in agenda['items']))
  self.assertTrue(all(i['context']['field']!='insurance.requirement' for i in agenda['items']))
 def test_answered_topics_disappear_but_document_based_current_details_need_confirmation(self):
  for _,_,fields,_ in TOPICS:
   for field in fields:self.c.execute('INSERT OR REPLACE INTO company_facts VALUES (?,?,?,?)',(field,'Provided','Reported by you',None))
  self.assertEqual(build_agenda(lambda:self.c)['items'],[])
  self.c.execute("UPDATE company_facts SET document_id='old-proposal' WHERE field='team.capacity'")
  item=build_agenda(lambda:self.c)['items'][0];self.assertEqual(item['id'],'team');self.assertEqual(item['status'],'Confirm current details')
 def test_selected_rfp_gaps_and_queued_followups_are_scoped(self):
  self.c.execute("INSERT INTO agent_runs VALUES ('selected',1)")
  for id in ['selected','other']:
   self.c.execute('INSERT INTO agent_analysis VALUES (?,?)',(id,json.dumps([{'text':id+' insurance requirement','status':'missing','gap_question':'What coverage can you document?'},{'text':'Supported item','status':'supported'}])))
  self.c.execute("INSERT INTO company_tasks VALUES ('t','Discuss privacy policy','Queued','compliance.privacy',1)")
  items=build_agenda(lambda:self.c)['items'];self.assertEqual(items[0]['context']['rfp_id'],'selected');self.assertEqual(items[-1]['label'],'Discuss privacy policy');self.assertFalse(any('other insurance'==i['label'] for i in items))
