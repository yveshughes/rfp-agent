"""Read-only review handoff. Delivery stays with the user and issuing agency."""
import json
from datetime import datetime,timezone
from urllib.parse import urlsplit


def register_response_review(app,db,workspace,data):
    @app.get('/api/rfps/{rfp_id}/review')
    async def review(rfp_id:str):
        saved=await workspace(rfp_id)
        versions={s['id']:s['version'] for s in saved['sections']}
        with db() as c:
            row=c.execute('SELECT requirements FROM agent_analysis WHERE rfp_id=?',(rfp_id,)).fetchone()
            pdfs=[dict(r) for r in c.execute('SELECT * FROM response_pdfs WHERE rfp_id=? ORDER BY created DESC',(rfp_id,))]
        requirements=json.loads(row['requirements']) if row else []
        current=next((p for p in pdfs if json.loads(p['versions'])==versions and p['title']==saved['rfp']['title'] and (data/'response-pdfs'/(p['id']+'.pdf')).is_file()),None)
        gaps=[r for r in requirements if r.get('status')!='supported']
        source=saved['rfp'].get('url','')
        expired=bool(saved['rfp'].get('deadline') and saved['rfp']['deadline']<datetime.now(timezone.utc).date().isoformat())
        closed=saved['rfp']['status'] in ('Responded','Closed — won','Closed — lost','Not pursuing')
        if urlsplit(source).scheme not in ('http','https'):source=''
        return {'rfp':saved['rfp'],'sections':saved['sections'],'requirements':requirements,'gaps':gaps,
                'pdf':{'id':current['id'],'pages':current['pages'],'url':'/api/response-pdfs/'+current['id']} if current else None,
                'ready':bool(current and not expired and not closed and all(s['body'].strip() for s in saved['sections'])),
                'expired':expired,'closed':closed,
                'source_url':source,'submission_connected':False}
    return review
