"""Open conversation topics derived from saved facts, never invented requirements."""
import json

# A topic is covered when these reusable basics have been supplied. Other profile
# fields remain editable; absent optional fields do not become mandatory RFP gaps.
TOPICS=[
 ('company','Company basics',['company.overview','company.contact'],'What should I know about your company?'),
 ('services','Services and experience',['experience.services','experience.projects'],'What services and relevant projects should we include?'),
 ('insurance','Current insurance',['insurance.coverage','insurance.limits','insurance.dates'],'Do you have a current insurance certificate we can add?'),
 ('registrations','Licenses and registrations',['registrations.licenses','registrations.supplier'],'Which licenses or supplier registrations do you hold, if any?'),
 ('certifications','Business certifications',['registrations.certifications'],'Do you hold any business certifications, or should we mark this as not applicable?'),
 ('team','Team and availability',['team.lead','team.capacity'],'Who would lead a new project, and what is your current availability?'),
 ('pricing','Current pricing',['pricing.rates','pricing.terms'],'How should we approach current rates and payment terms?'),
 ('references','Reference contacts',['references.contacts','references.permission'],'Which clients can we contact as references, with their permission?'),
]
CURRENT_FIELDS={'insurance.coverage','insurance.limits','insurance.dates','team.capacity','pricing.rates','references.permission'}

def build_agenda(db):
    with db() as c:
        facts={r['field']:dict(r) for r in c.execute('SELECT * FROM company_facts')}
        tasks=[dict(r) for r in c.execute("SELECT * FROM company_tasks WHERE status='Queued' ORDER BY created")]
        run=c.execute('SELECT rfp_id FROM agent_runs ORDER BY created DESC LIMIT 1').fetchone()
        requirements=[]
        if run and run['rfp_id']:
            analysis=c.execute('SELECT requirements FROM agent_analysis WHERE rfp_id=?',(run['rfp_id'],)).fetchone()
            if analysis:requirements=json.loads(analysis['requirements'])
    items=[]
    for i,req in enumerate(requirements):
        if req.get('status') not in ('missing','needs_confirmation'):continue
        question=req.get('gap_question') or 'What information can we add to address this requirement?'
        items.append({'id':f'rfp-{i}','label':req['text'],'status':'RFP question','question':question,'context':{'rfp_id':run['rfp_id'],'section':'files'}})
    covered=0
    for id,label,fields,question in TOPICS:
        missing=[f for f in fields if not str(facts.get(f,{}).get('value','')).strip() or facts.get(f,{}).get('status') in ('Unknown','Gap reported')]
        historical=[f for f in fields if f in CURRENT_FIELDS and facts.get(f,{}).get('document_id')]
        if not missing and not historical:covered+=1;continue
        field=(missing or historical)[0]
        items.append({'id':id,'label':label,'status':'Not added' if missing else 'Confirm current details','question':question,'context':{'field':field}})
    for task in tasks:
        if any(item['context'].get('field')==task['field'] for item in items):continue
        items.append({'id':'task-'+task['id'],'label':task['title'],'status':'Queued follow-up','question':'What do we need to resolve for this follow-up?','context':{'field':task['field']}})
    return {'items':items,'covered':covered,'total_profile_topics':len(TOPICS)}
