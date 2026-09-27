"""Small, source-backed document review receipt for the Activity preview."""
import json
from app.chat_outcomes import _object


def current_document_review(c,messages,steps):
    user=next((m for m in reversed(messages) if m['role']=='user'),None)
    if not user:return None
    reads=[]
    for step in steps:
        if step['created']<user['created'] or step['tool']!='read_document':continue
        result=_object(step['result'])
        if result.get('error') or not result.get('id') or not isinstance(result.get('pages'),list):continue
        reads.append({**result,'reviewed_at':step['created']})
    doc_id=reads[-1]['id'] if reads else next((a['id'] for a in user.get('attachments',[])),None)
    if not doc_id:return None
    row=c.execute('SELECT id,name,media_type,first_page,last_page,total_pages,pages FROM documents WHERE id=?',(doc_id,)).fetchone()
    if not row:return None
    doc=dict(row);saved_pages=json.loads(doc.pop('pages'))
    seen={p.get('page') for r in reads if r['id']==doc_id for p in r['pages'] if isinstance(p,dict)}
    doc['reviewed_pages']=len(seen & {p['page'] for p in saved_pages})
    doc['extracted_pages']=len(saved_pages)
    doc['reviewed_at']=reads[-1]['reviewed_at'] if reads else user['created']
    return doc
