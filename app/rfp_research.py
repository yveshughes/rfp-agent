"""Fetch only recorded RFP sources and links discovered from them."""
import hashlib
import json
import time
import uuid
from urllib.parse import urlsplit
from app.opportunities import Page, canonical


class RFPResearch:
    def __init__(self,db,data,fetch,store_pdf,require_rfp,event):
        self.db,self.data,self.fetch,self.store_pdf,self.require_rfp,self.event=db,data,fetch,store_pdf,require_rfp,event
        with db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS rfp_source_pages(rfp_id TEXT,url TEXT,links TEXT,PRIMARY KEY(rfp_id,url))')

    async def read(self,rfp_id,url=None):
        rfp=self.require_rfp(rfp_id)
        if not rfp['url']:raise ValueError('This opportunity has no saved source URL. An original RFP is needed.')
        url=url or rfp['url']
        allowed={canonical(rfp['url'])}
        with self.db() as c:
            for row in c.execute('SELECT url,links FROM rfp_source_pages WHERE rfp_id=?',(rfp_id,)):
                allowed.add(canonical(row['url']))
                allowed.update(canonical(link['url']) for link in json.loads(row['links']))
        if canonical(url) not in allowed:raise ValueError('Use the saved RFP source or a link returned by read_rfp_source.')
        raw,final=await self.fetch(url)
        if raw.startswith(b'%PDF'):
            saved=await self.store_pdf(raw,urlsplit(final).path.split('/')[-1] or 'RFP.pdf',rfp_id=rfp_id,source_url=final,automatic=True)
            return {'url':final,'document':saved,'instruction':'Read all extracted pages with read_document. Check extraction limits before claiming full coverage.'}
        page=Page(raw.decode('utf-8',errors='replace'),final)
        links=list({canonical(link['url']):link for link in page.links}.values())[:100]
        text=page.text.strip()
        if len(text)<80:raise ValueError('The source did not provide enough readable text. Try an original attachment or another candidate.')
        clipped=len(text)>120000;text=text[:120000]
        chunks=[{'page':i//6000+1,'text':text[i:i+6000]} for i in range(0,len(text),6000)]
        digest=hashlib.sha256((final+'\n'+text).encode()).hexdigest()
        with self.db() as c:
            existing=c.execute('SELECT id FROM documents WHERE rfp_id=? AND sha256=?',(rfp_id,digest)).fetchone()
        doc_id=existing['id'] if existing else uuid.uuid4().hex
        if not existing:
            (self.data/(doc_id+'.txt')).write_text('Source: '+final+'\n\n'+text)
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO rfp_source_pages VALUES (?,?,?)',(rfp_id,final,json.dumps(links)))
            if not existing:
                note='Saved agency webpage. Excerpt numbers are not PDF page numbers.'+(' Text was truncated; inspect the original for omitted details.' if clipped else '')
                c.execute('INSERT INTO documents(id,name,first_page,last_page,added,pages,rfp_id,source_url,sha256,total_pages,media_type,file_ext,extraction_note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (doc_id,rfp['title'][:170]+' — source.txt',1,len(chunks),time.time(),json.dumps(chunks),rfp_id,final,digest,len(chunks),'text/plain','.txt',note))
        self.event('research','RFP source reviewed',rfp['title'])
        return {'url':final,'document':{'id':doc_id,'pages':len(chunks)},'text_excerpt':text[:10000],'truncated':clipped or len(text)>10000,'links':links,
                'instruction':'Read all saved excerpts with read_document; inspect original attachments and addenda before drafting. This source may be only a listing, not complete RFP requirements.'}
