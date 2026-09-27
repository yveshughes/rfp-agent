"""Evidence-aware company facts and guided conversations; no model claims."""
import re
import time
import uuid
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

def stated_limit(text):
    """Only one explicit, unambiguous dollar amount; do not equate limit bases."""
    matches=list(re.finditer(r'(?<![\w.])\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(million|thousand|m\b|k\b)?', text, re.I))
    values=[]
    for m in matches:
        if not m.group(2) and '$' not in m.group(): continue
        n=float(m.group(1).replace(',','')) * ({'m':1e6,'million':1e6,'k':1e3,'thousand':1e3}.get((m.group(2) or '').lower(),1))
        if n>0: values.append(n)
    return values[0] if len(values)==1 else None

def insurance_details(text):
    # Questions, uncertain answers and hypothetical purchases are not current policies.
    if re.search(r'\?|\b(if|would|could|should|might|maybe|not sure|unsure|need|want|requires?|requirements?|rfp|used to|previous|formerly|deductible|premium|cost|quote|excess|umbrella|workers|professional)\b|\b(?:don.t|do not) have\b',text,re.I): return {}
    if not re.search(r'\b(?:we|i)\s+(?:currently\s+)?(?:have|carry|hold)|\bour\s+(?:policy|coverage|insurance)|\binsured\b',text,re.I): return {}
    details={}
    amount=stated_limit(text)
    if amount: details['insurance.limits']=f'${amount:,.0f} reported limit; occurrence / aggregate basis not yet confirmed'
    if re.search(r'\bHartford\b',text,re.I): details['insurance.insurer']='The Hartford (reported by you)'
    return details

class ProfileAnswer(BaseModel):
    field: str
    text: str = Field(max_length=6000)
    action: str = 'answer'
    conversation: str = Field(default='',max_length=160)

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
        CREATE TABLE IF NOT EXISTS company_dialogue(field TEXT PRIMARY KEY,stage TEXT);
        CREATE TABLE IF NOT EXISTS company_web_pages(id TEXT PRIMARY KEY,run_id TEXT,url TEXT,title TEXT,body TEXT,checked REAL,links TEXT);
        CREATE TABLE IF NOT EXISTS company_web_evidence(field TEXT PRIMARY KEY,page_id TEXT,quote TEXT);
        CREATE TRIGGER IF NOT EXISTS clear_company_web_insert AFTER INSERT ON company_facts BEGIN DELETE FROM company_web_evidence WHERE field=NEW.field; END;
        CREATE TRIGGER IF NOT EXISTS clear_company_web_update AFTER UPDATE ON company_facts BEGIN DELETE FROM company_web_evidence WHERE field=NEW.field; END;
        CREATE TRIGGER IF NOT EXISTS clear_company_web_delete AFTER DELETE ON company_facts BEGIN DELETE FROM company_web_evidence WHERE field=OLD.field; END;
        ''')

    def check_field(field):
        if field not in FIELDS: raise HTTPException(400,'Unknown company field.')

    def message(c,field,role,text):
        c.execute('INSERT INTO company_messages(field,role,text,at) VALUES (?,?,?,?)',(field,role,text,time.time()))

    def fact(c,field,value,status):
        # A new statement invalidates prior evidence; it never inherits verification.
        c.execute('INSERT OR REPLACE INTO company_facts VALUES (?,?,?,?,?,?)',(field,value,status,None,None,time.time()))

    def task(c,field,kind,title):
        c.execute('INSERT OR IGNORE INTO company_tasks VALUES (?,?,?,?,?,?)',(uuid.uuid4().hex,field,kind,title,'Queued',time.time()))

    @app.get('/api/company')
    async def company_profile():
        with db() as c:
            facts={r['field']:dict(r) for r in c.execute('SELECT * FROM company_facts')}
            for source in c.execute('SELECT e.field,e.quote AS source_quote,p.url AS source_url,p.title AS source_title,p.checked AS source_checked FROM company_web_evidence e JOIN company_web_pages p ON p.id=e.page_id'):
                if source['field'] in facts: facts[source['field']].update(dict(source))
            messages=[dict(r) for r in c.execute('SELECT * FROM company_messages ORDER BY id')]
            tasks=[dict(r) for r in c.execute('SELECT * FROM company_tasks ORDER BY created DESC')]
        return {'sections':SCHEMA,'facts':facts,'messages':messages,'tasks':tasks}

    @app.post('/api/company/chat')
    async def company_chat(req:ProfileAnswer):
        check_field(req.field)
        text=req.text.strip()
        if not text and req.action!='edit': raise HTTPException(400,'Add an answer first.')
        if req.action not in ('answer','ask','insurance_example','edit'): raise HTTPException(400,'Unknown conversation action.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            facts_before=[tuple(r) for r in c.execute('SELECT * FROM company_facts ORDER BY field')]
            tasks_before=c.execute('SELECT COUNT(*) FROM company_tasks').fetchone()[0]
            dialogue_key=req.field+('@'+req.conversation if req.conversation else '')
            row=c.execute('SELECT stage FROM company_dialogue WHERE field=?',(dialogue_key,)).fetchone()
            stage=row['stage'] if row else ''
            if req.action=='edit':
                previous=c.execute('SELECT value FROM company_facts WHERE field=?',(req.field,)).fetchone()
                if not text:
                    c.execute('DELETE FROM company_facts WHERE field=?',(req.field,))
                elif not previous or previous['value']!=text:
                    fact(c,req.field,text,'Reported by you')
                message(c,req.field,'user',f'Direct edit: {text}' if text else 'Cleared this company detail.')
                reply='Saved your edit.' if text else 'Cleared this detail.'
                stage=''
                prefix=req.field+'@'
                c.execute('DELETE FROM company_dialogue WHERE field=? OR substr(field,1,?)=?',(req.field,len(prefix),prefix))
            elif req.action=='insurance_example':
                if req.field!='insurance.coverage': raise HTTPException(400,'Choose insurance coverage for this example.')
                message(c,req.field,'user','Walk me through the $5M liability insurance example.')
                reply='Do you have $5M in general liability insurance? This is an example requirement; I’ll need the actual RFP wording and policy documents to assess a match.'
                stage='coverage_answer_example'
            elif req.action=='ask':
                message(c,req.field,'user',f'Let’s review {FIELDS[req.field].lower()}.')
                reply=('Do you have a current insurance certificate we can add? If not, tell me what coverage you have.' if req.field=='insurance.coverage' else f'What should I record for {FIELDS[req.field].lower()}? Tell me in your own words.')
                stage='coverage_answer' if req.field=='insurance.coverage' else ''
            else:
                message(c,req.field,'user',text)
                normalized=text.lower().strip(' .!?')
                normalized=normalized.replace('’', "'")
                yes=normalized in ('yes','yes please','please do','research options','yes, research options')
                no=normalized in ('no','no thanks','not now')
                unsure=bool(re.search(r"\b(not sure|unsure|uncertain|don't know|do not know)\b",normalized))
                coverage_no=not unsure and bool(re.search(r"^(no\b|nope\b)|\b(don't have|do not have|without coverage|not insured|uninsured|no coverage)\b",normalized))
                question=bool('?' in text or re.match(r'^(does|do|can|could|would|should|what|how|why|is|are)\b',normalized))
                hypothetical=req.field=='insurance.coverage' and bool(re.search(r'\b(if|would|could|might|maybe|need|want|requires?|requirements?|rfp|used to|previous|formerly)\b',normalized)) and not unsure
                if question or hypothetical:
                    reply='I haven’t changed your company facts. Tell me what coverage you currently have; put the RFP’s exact wording in the coverage requirement field so we can compare the two.' if req.field.startswith('insurance.') else 'I haven’t changed this detail. Tell me what you want recorded, or link a supporting document for review.'
                elif stage.startswith('research_offer'):
                    if yes:
                        task(c,req.field,'research','Research liability insurance options & application requirements')
                        reply='Added to my to-do list: research liability insurance options and application requirements. It’s queued for follow-up. No application has been sent and no policy will be purchased without your approval.'
                        stage=''
                    elif no:
                        reply='Understood. I’ve kept the coverage gap in your profile without adding a research task.'
                        stage=''
                    else:
                        reply='Would you like me to add insurance research to my to-do list? Say “yes” or “not now.” Your coverage details haven’t changed.'
                elif req.field=='insurance.coverage':
                    fact(c,req.field,text,'Gap reported' if coverage_no else 'Unknown' if unsure else 'Reported by you')
                    details=insurance_details(text) if not unsure and not coverage_no else {}
                    for key,value in details.items(): fact(c,key,value,'Reported by you')
                    limit=stated_limit(text) if details else None
                    requirement=c.execute("SELECT value FROM company_facts WHERE field='insurance.requirement'").fetchone()
                    target=5e6 if stage=='coverage_answer_example' else stated_limit(requirement['value']) if requirement else None
                    if coverage_no:
                        reply='I’ve recorded that coverage is missing for this question. Would you like me to research policies and the steps to get an application started?'
                        stage='research_offer'
                    elif limit and target and limit<target:
                        source='the illustrative $5M example' if stage=='coverage_answer_example' else 'the requirement saved in your company profile'
                        reply=f'I’ve saved your ${limit:,.0f} liability limit'+(' and The Hartford as your insurer' if 'insurance.insurer' in details else '')+f'. It is lower than the ${target:,.0f} in {source}. We still need to check the policy’s occurrence and aggregate terms. Should I add research into increasing your coverage to my to-do list?'
                        stage='research_offer'
                    else:
                        task(c,req.field,'verify','Verify liability coverage, limits, dates & endorsements')
                        reply=('I’ve saved your reported limit'+(' and The Hartford as your insurer' if 'insurance.insurer' in details else '')+' in your company profile. ' if details else 'I’ve recorded your answer. ')+'I’ve queued a coverage verification task. Add your certificate or policy under Documents so we can check the limit basis, dates, and actual RFP wording.'
                        stage=''
                else:
                    fact(c,req.field,text,'Unknown' if unsure else 'Reported by you')
                    reply=f'Updated {FIELDS[req.field].lower()} in your company profile. It’s marked {"unknown" if unsure else "reported by you"}. You can link a supporting document when you have it.'
            c.execute('INSERT OR REPLACE INTO company_dialogue VALUES (?,?)',(dialogue_key,stage))
            message(c,req.field,'billy',reply)
            facts_changed=facts_before!=[tuple(r) for r in c.execute('SELECT * FROM company_facts ORDER BY field')]
            tasks_added=c.execute('SELECT COUNT(*) FROM company_tasks').fetchone()[0]>tasks_before
        if facts_changed: event('profile','Company profile updated',FIELDS[req.field])
        if tasks_added: event('profile','Company follow-up queued',FIELDS[req.field])
        return {'reply':reply, 'profile':await company_profile()}

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
            c.execute('DELETE FROM company_dialogue WHERE field=?',(req.field,))
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

    return company_profile, company_chat, company_evidence, company_task
