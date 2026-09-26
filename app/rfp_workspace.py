"""Persistent RFP response sections, manual completion checks, and scoped notes."""
import json
import time
from fastapi import HTTPException
from pydantic import BaseModel, Field

STARTERS = {
    '1': ('Qualifications', ['Confirm the requested qualifications', 'Describe relevant experience', 'Identify the delivery team', 'Add supporting references', 'Review this section against the RFP']),
    '2': ('Approach & delivery', ['Confirm the scope of work', 'Describe the proposed approach', 'Define deliverables', 'Confirm timeline and milestones', 'Review this section against the RFP']),
    '3': ('Pricing & compliance', ['Confirm the pricing format', 'Add fees and assumptions', 'Check insurance and eligibility', 'Confirm required declarations', 'Review this section against the RFP']),
}

class ResponseCheck(BaseModel):
    text: str = Field(min_length=1,max_length=500)
    done: bool = False

class ResponseSection(BaseModel):
    title: str = Field(min_length=1,max_length=100)
    body: str = Field(default='',max_length=50000)
    checks: list[ResponseCheck] = Field(min_length=1,max_length=40)
    version: int = Field(default=0,ge=0)

class ResponseNote(BaseModel):
    text: str = Field(min_length=1,max_length=6000)


def register_rfp_workspace(app, db, require_rfp, event):
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS response_sections(rfp_id TEXT,section_id TEXT,title TEXT,body TEXT,checks TEXT,version INTEGER,updated REAL,PRIMARY KEY(rfp_id,section_id));
        CREATE TABLE IF NOT EXISTS response_notes(id INTEGER PRIMARY KEY,rfp_id TEXT,section_id TEXT,text TEXT,at REAL);
        ''')

    def sections(rfp_id):
        with db() as c: rows={r['section_id']:dict(r) for r in c.execute('SELECT * FROM response_sections WHERE rfp_id=?',(rfp_id,))}
        result=[]
        for key,(title,checks) in STARTERS.items():
            row=rows.get(key)
            s={'id':key,'title':row['title'] if row else title,'body':row['body'] if row else '',
               'checks':json.loads(row['checks']) if row else [{'text':v,'done':False} for v in checks],
               'version':row['version'] if row else 0,'updated':row['updated'] if row else None}
            s['progress']=round(100*sum(v['done'] for v in s['checks'])/len(s['checks']))
            result.append(s)
        return result

    @app.get('/api/rfps/{rfp_id}/workspace')
    async def rfp_workspace(rfp_id:str):
        rfp=require_rfp(rfp_id)
        parts=sections(rfp_id)
        with db() as c:
            notes=[dict(r) for r in c.execute('SELECT * FROM response_notes WHERE rfp_id=? ORDER BY id',(rfp_id,))]
        total=sum(len(s['checks']) for s in parts)
        done=sum(sum(v['done'] for v in s['checks']) for s in parts)
        return {'rfp':rfp,'sections':parts,'notes':notes,'progress':round(100*done/total),'completed':done,'total':total}

    @app.post('/api/rfps/{rfp_id}/sections/{section_id}')
    async def save_response_section(rfp_id:str,section_id:str,req:ResponseSection):
        require_rfp(rfp_id)
        if section_id not in STARTERS: raise HTTPException(404,'Response section not found.')
        if not req.title.strip() or any(not c.text.strip() for c in req.checks): raise HTTPException(400,'Give the section and each checklist item a name.')
        if all(c.done for c in req.checks) and not req.body.strip(): raise HTTPException(400,'Add the response draft before marking every check complete.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT version FROM response_sections WHERE rfp_id=? AND section_id=?',(rfp_id,section_id)).fetchone()
            if req.version!=(old['version'] if old else 0): raise HTTPException(409,'This section changed in another session. Your draft is kept here; reopen the RFP to load the latest version before saving.')
            c.execute('INSERT OR REPLACE INTO response_sections VALUES (?,?,?,?,?,?,?)',(rfp_id,section_id,req.title.strip(),req.body,json.dumps([{'text':x.text.strip(),'done':x.done} for x in req.checks]),req.version+1,time.time()))
        event('done','Response section saved',req.title.strip())
        return await rfp_workspace(rfp_id)

    @app.post('/api/rfps/{rfp_id}/discussion/{section_id}')
    async def add_response_note(rfp_id:str,section_id:str,req:ResponseNote):
        require_rfp(rfp_id)
        if section_id not in (*STARTERS,'files'): raise HTTPException(404,'Response section not found.')
        if not req.text.strip(): raise HTTPException(400,'Write a note first.')
        with db() as c:
            c.execute('INSERT INTO response_notes(rfp_id,section_id,text,at) VALUES (?,?,?,?)',(rfp_id,section_id,req.text.strip(),time.time()))
        return await rfp_workspace(rfp_id)

    return rfp_workspace, save_response_section, add_response_note
