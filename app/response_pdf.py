"""Immutable review copies of saved response sections; never a submission."""
import hashlib
import io
import json
import time
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pypdf import PdfReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer


def render_response(title, sections):
    output=io.BytesIO()
    doc=SimpleDocTemplate(output,pagesize=letter,rightMargin=54,leftMargin=54,topMargin=54,bottomMargin=54,
                         title=title,author='RFP Agent',pageCompression=1)
    body=ParagraphStyle('Body',fontName='Times-Roman',fontSize=12,leading=14,spaceAfter=7)
    heading=ParagraphStyle('Heading',parent=body,fontName='Times-Bold',spaceBefore=9,keepWithNext=True)
    def text(value):
        return escape(value.replace('\u2011','-').replace('\u2013','-').replace('\u2014','-'))
    story=[Paragraph(text(title),heading),Spacer(1,8)]
    for section in sections:
        story.append(Paragraph(text(section['title']),heading))
        story.extend(Paragraph(text(p).replace('\n','<br/>'),body) for p in section['body'].split('\n\n') if p.strip())
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('Times-Roman',9)
        canvas.drawString(54,30,'REVIEW COPY - confirm facts, terms and unresolved placeholders before submission')
        canvas.drawRightString(letter[0]-54,30,str(doc.page));canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    raw=output.getvalue()
    return raw,len(PdfReader(io.BytesIO(raw)).pages)


def register_response_pdf(app,db,data,workspace,event):
    folder=Path(data)/'response-pdfs';folder.mkdir(parents=True,exist_ok=True)
    with db() as c:c.execute('CREATE TABLE IF NOT EXISTS response_pdfs(id TEXT PRIMARY KEY,rfp_id TEXT,name TEXT,versions TEXT,pages INTEGER,created REAL)')

    async def export(rfp_id):
        saved=await workspace(rfp_id)
        sections=saved['sections']
        if any(not s['body'].strip() for s in sections):raise ValueError('Save all three response sections before creating the review PDF.')
        versions={s['id']:s['version'] for s in sections}
        digest=hashlib.sha256(json.dumps({'rfp':rfp_id,'sections':sections},sort_keys=True).encode()).hexdigest()[:32]
        with db() as c:existing=c.execute('SELECT * FROM response_pdfs WHERE id=?',(digest,)).fetchone()
        if existing:pages=existing['pages']
        else:
            raw,pages=render_response(saved['rfp']['title'],sections)
            (folder/(digest+'.pdf')).write_bytes(raw)
            with db() as c:c.execute('INSERT INTO response_pdfs VALUES (?,?,?,?,?,?)',(digest,rfp_id,'Response - review copy.pdf',json.dumps(versions),pages,time.time()))
            event('done','Response PDF ready for review',f'{pages} pages; review required before any submission.')
        return {'id':digest,'rfp_id':rfp_id,'name':'Response - review copy.pdf','pages':pages,'versions':versions,
                'url':'/api/response-pdfs/'+digest,'review_required':True,
                'note':'Check page limits, placeholders, signatures and required attachments. This PDF has not been submitted.'}

    @app.get('/api/response-pdfs')
    async def list_pdfs():
        with db() as c:rows=[dict(r) for r in c.execute('SELECT * FROM response_pdfs ORDER BY created DESC')]
        for row in rows:
            current=await workspace(row['rfp_id'])
            row['stale']=json.loads(row['versions'])!={s['id']:s['version'] for s in current['sections']}
            row['url']='/api/response-pdfs/'+row['id']
        return rows

    @app.get('/api/response-pdfs/{pdf_id}')
    async def download(pdf_id:str):
        with db() as c:row=c.execute('SELECT name FROM response_pdfs WHERE id=?',(pdf_id,)).fetchone()
        if not row:raise HTTPException(404,'Response PDF not found.')
        return FileResponse(folder/(pdf_id+'.pdf'),media_type='application/pdf',filename=row['name'],content_disposition_type='inline')

    return export
