"""Customer-facing receipts built only from successful, saved agent actions."""
import json
from app.company import FIELDS


def _object(raw):
    try:
        value=json.loads(raw)
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError):
        return {}


def attach_outcomes(c, messages, steps):
    """Attach work to its original reply, never to a later unrelated question."""
    for message in messages:
        if message['role']!='billy':continue
        # A resumed job can contain several user messages before its first reply.
        # Carry successful, not-yet-reported work through those interruptions.
        previous=max((m['created'] for m in messages if m['role']=='billy' and m['id']<message['id']),default=0)
        website=False;fields=set();cards={}
        for step in steps:
            if not previous<step['created']<=message['created']:continue
            result=_object(step['result']);args=_object(step['arguments'])
            if not result or result.get('error') or (result.get('truncated') and 'data_excerpt' in result) or result.get('already_completed'):continue
            if step['tool']=='read_company_website' and result.get('web_page_id'):website=True
            if step['tool']=='save_fact' and result.get('field') in FIELDS:fields.add(result['field'])
            if step['tool']=='pursue' and result.get('selected'):
                cards[result['selected']]={'id':result['selected'],'reason':str(result.get('reason',''))[:500],'selected':True}
            if step['tool']=='recommend':
                for item in result.get('recommendations',[]):
                    if isinstance(item,dict) and item.get('id'):
                        cards.setdefault(item['id'],{'id':item['id'],'reason':str(item.get('reason',''))[:500],'selected':False})
        actions=[]
        if website:actions.append('reviewed your website')
        if fields:actions.append('updated your company profile')
        summary=('I '+(' and '.join(actions))+'.') if actions else ''
        rfps=[]
        for card in list(cards.values())[:4]:
            row=c.execute('SELECT id,title,agency,deadline FROM rfps WHERE id=?',(card['id'],)).fetchone()
            if not row:continue
            # A saved original is required. Never invent a cover or fetch an arbitrary URL here.
            doc=c.execute('SELECT id FROM documents WHERE rfp_id=? ORDER BY added DESC LIMIT 1',(card['id'],)).fetchone()
            rfps.append({**dict(row),**card,'preview_document_id':doc['id'] if doc else None})
        if summary or rfps:
            message['outcome']={'summary':summary,'profile_updated':bool(fields),'profile_fields':[FIELDS[f] for f in sorted(fields)],'rfps':rfps}
