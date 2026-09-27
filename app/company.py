"""Company profile schema, direct edits, evidence links and follow-up tasks; no model claims."""
import time
from fastapi import HTTPException
from pydantic import BaseModel, Field

SECTIONS = [
    ('company', 'Company', 'The essentials behind every response.', [('legal_name','Legal company name'),('overview','Company overview'),('website','Website'),('address','Business address'),('contact','Proposal contact')]),
    ('registrations','Registrations','Business identifiers and eligibility.', [('entity','Entity type & jurisdiction'),('tax','Tax registration status'),('licenses','Business & professional licenses'),('supplier','Supplier registrations'),('certifications','Small business & diversity certifications')]),
    ('experience','Experience','Your capabilities, relevant work, and results.', [('services','Services & capabilities'),('sectors','Sectors served'),('projects','Relevant projects'),('results','Outcomes & differentiators')]),
    ('team','Team','The people who will deliver the work.', [('lead','Project lead'),('staff','Key staff & qualifications'),('capacity','Availability & capacity'),('partners','Partners & subcontractors')]),
    ('insurance','Insurance','Coverage, supporting documents, and gaps to resolve.', [('requirement','RFP coverage requirement'),('coverage','General liability coverage'),('insurer','Insurer & broker'),('policy','Policy number'),('limits','Per-occurrence & aggregate limits'),('dates','Effective & expiration dates'),('other','Professional, workers’ comp & other coverage'),('exclusions','Exclusions & endorsements')]),
    ('compliance','Compliance','The policies and commitments buyers ask about.', [('security','Information security'),('privacy','Privacy & data handling'),('accessibility','Accessibility'),('conflicts','Conflicts of interest'),('declarations','Required declarations')]),
    ('pricing','Pricing','Commercial details you can reuse and review.', [('rates','Rate card'),('approach','Pricing approach'),('terms','Payment terms'),('assumptions','Assumptions & exclusions')]),
    ('references','References','People and projects that support your track record.', [('clients','Client references'),('contacts','Reference contacts'),('permission','Permission to share references')]),
]
SCHEMA = [{'id':s,'name':n,'description':d,'fields':[{'id':f'{s}.{k}','label':label} for k,label in fields]} for s,n,d,fields in SECTIONS]
FIELDS = {f['id']:f['label'] for s in SCHEMA for f in s['fields']}


class ProfileEdit(BaseModel):
    value: str = Field(default='',max_length=6000)

class ProfileEvidence(BaseModel):
    field: str
    document_id: str
    page: int = Field(ge=1)
    value: str = Field(min_length=1,max_length=6000)

class ProfileTaskUpdate(BaseModel):
    status: str


def register_company(app, db, event):
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS company_facts(field TEXT PRIMARY KEY,value TEXT,status TEXT,document_id TEXT,page INTEGER,updated REAL);
        CREATE TABLE IF NOT EXISTS company_messages(id INTEGER PRIMARY KEY,field TEXT,role TEXT,text TEXT,at REAL);
        CREATE TABLE IF NOT EXISTS company_tasks(id TEXT PRIMARY KEY,field TEXT,kind TEXT,title TEXT,status TEXT,created REAL);
        CREATE UNIQUE INDEX IF NOT EXISTS company_open_task ON company_tasks(field,kind) WHERE status='Queued';
        CREATE TABLE IF NOT EXISTS company_web_pages(id TEXT PRIMARY KEY,run_id TEXT,url TEXT,title TEXT,body TEXT,checked REAL,links TEXT);
        CREATE TABLE IF NOT EXISTS company_web_evidence(field TEXT PRIMARY KEY,page_id TEXT,quote TEXT);
        CREATE TRIGGER IF NOT EXISTS clear_company_web_insert AFTER INSERT ON company_facts BEGIN DELETE FROM company_web_evidence WHERE field=NEW.field; END;
        CREATE TRIGGER IF NOT EXISTS clear_company_web_update AFTER UPDATE ON company_facts BEGIN DELETE FROM company_web_evidence WHERE field=NEW.field; END;
        CREATE TRIGGER IF NOT EXISTS clear_company_web_delete AFTER DELETE ON company_facts BEGIN DELETE FROM company_web_evidence WHERE field=OLD.field; END;
        ''')

    def check_field(field):
        if field not in FIELDS: raise HTTPException(400,'Unknown company field.')

    def message(c,field,role,text):
        # company_messages is the per-field audit trail: edits, evidence links and task changes.
        c.execute('INSERT INTO company_messages(field,role,text,at) VALUES (?,?,?,?)',(field,role,text,time.time()))

    @app.get('/api/company')
    async def company_profile():
        with db() as c:
            facts={r['field']:dict(r) for r in c.execute('SELECT * FROM company_facts')}
            for source in c.execute('SELECT e.field,e.quote AS source_quote,p.url AS source_url,p.title AS source_title,p.checked AS source_checked FROM company_web_evidence e JOIN company_web_pages p ON p.id=e.page_id'):
                if source['field'] in facts: facts[source['field']].update(dict(source))
            messages=[dict(r) for r in c.execute('SELECT * FROM company_messages ORDER BY id')]
            tasks=[dict(r) for r in c.execute('SELECT * FROM company_tasks ORDER BY created DESC')]
        return {'sections':SCHEMA,'facts':facts,'messages':messages,'tasks':tasks}

    @app.post('/api/company/facts/{field}')
    async def company_edit(field:str,req:ProfileEdit):
        check_field(field)
        value=req.value.strip()
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            previous=c.execute('SELECT value FROM company_facts WHERE field=?',(field,)).fetchone()
            if not value:
                changed=bool(previous)
                c.execute('DELETE FROM company_facts WHERE field=?',(field,))
            else:
                changed=not previous or previous['value']!=value
                # A new statement invalidates prior evidence; it never inherits verification.
                if changed: c.execute('INSERT OR REPLACE INTO company_facts VALUES (?,?,?,?,?,?)',(field,value,'Reported by you',None,None,time.time()))
            message(c,field,'user',f'Direct edit: {value}' if value else 'Cleared this company detail.')
        if changed: event('profile','Company profile updated',FIELDS[field])
        return await company_profile()

    @app.post('/api/company/evidence')
    async def company_evidence(req:ProfileEvidence):
        check_field(req.field)
        value=req.value.strip()
        if not value: raise HTTPException(400,'Record the detail supported by this page.')
        with db() as c:
            row=c.execute('SELECT * FROM documents WHERE id=?',(req.document_id,)).fetchone()
            if not row: raise HTTPException(404,'Supporting document not found.')
            total=row['total_pages'] or row['last_page']
            if req.page>total: raise HTTPException(400,'That page is outside the original document.')
            c.execute('INSERT OR REPLACE INTO company_facts VALUES (?,?,?,?,?,?)',(req.field,value,'Evidence linked',req.document_id,req.page,time.time()))
            message(c,req.field,'user',f'Linked {row["name"]}, page {req.page}: {value}')
            message(c,req.field,'billy','Saved with the original page attached. This records your supporting evidence; independent policy verification and RFP compliance review are still pending.')
        event('profile','Company evidence linked',FIELDS[req.field])
        return await company_profile()

    @app.post('/api/company/tasks/{task_id}')
    async def company_task(task_id:str,req:ProfileTaskUpdate):
        if req.status not in ('Queued','Done','Cancelled'): raise HTTPException(400,'Unknown task status.')
        with db() as c:
            row=c.execute('SELECT * FROM company_tasks WHERE id=?',(task_id,)).fetchone()
            if not row: raise HTTPException(404,'Task not found.')
            if req.status=='Queued' and c.execute("SELECT id FROM company_tasks WHERE field=? AND kind=? AND status='Queued' AND id!=?",(row['field'],row['kind'],task_id)).fetchone():
                raise HTTPException(409,'This follow-up is already queued.')
            c.execute('UPDATE company_tasks SET status=? WHERE id=?',(req.status,task_id))
            message(c,row['field'],'user',f'Marked follow-up {req.status.lower()}: {row["title"]}')
        event('profile','Company follow-up '+req.status.lower(),row['title'])
        return await company_profile()

    return company_profile, company_edit, company_evidence, company_task
