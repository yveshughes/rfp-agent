"""Persistent watched-source discovery and explainable, preliminary company fit."""
import asyncio
import json
import re
import time
import uuid
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from fastapi import HTTPException

STOP = set('the a an and or of to in for with on by from is are be this that as at our your we you will shall must may have has it its can all not their they include including services service project projects proposal proposals request requirements company work based completed require qualifications current confirm confirmation documentation document documents detail details original page pages demo march september october january february april june july august november december year years experience technical provide providing preparation prepared public city county department bid bids rfp rfps qualified consultant consultants required support contract scope submission submit response responses following'.split())
FIELDS = ('company.overview', 'experience.services', 'experience.sectors', 'experience.projects')

def canonical(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/') or '/', p.query, ''))

def tokens(text):
    return {w for w in re.findall(r'[a-z][a-z0-9-]{2,}', text.lower()) if w not in STOP}

class Page(HTMLParser):
    """Read public listing rows, links, and main text without executing site code."""
    def __init__(self, html, url):
        super().__init__(convert_charrefs=True)
        self.url=url; self.links=[]; self.rows=[]; self.parts=[]; self.main=[]
        self.skip=0; self.main_depth=0; self.anchor=None; self.row=None; self.rfp_table=False
        self.feed(html)
        self.text=' '.join(self.main or self.parts)
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if 'view-id-rfps' in attrs.get('class','').split(): self.rfp_table=True
        if tag in ('script','style','nav','header','footer'): self.skip+=1
        if tag=='main': self.main_depth+=1
        if self.skip: return
        if tag=='tr': self.row={'text':[], 'links':[]}
        if tag=='a' and attrs.get('href'):
            url=urljoin(self.url,attrs['href'])
            if urlsplit(url).scheme in ('https','http'):
                self.anchor={'url':canonical(url),'parts':[], 'rel':attrs.get('rel','')}
    def handle_data(self, data):
        if self.skip or not data.strip(): return
        text=' '.join(data.split()); self.parts.append(text)
        if self.main_depth: self.main.append(text)
        if self.row is not None: self.row['text'].append(text)
        if self.anchor is not None: self.anchor['parts'].append(text)
    def handle_endtag(self, tag):
        if tag in ('script','style','nav','header','footer'): self.skip=max(0,self.skip-1)
        if tag=='main': self.main_depth=max(0,self.main_depth-1)
        if self.skip: return
        if tag=='a' and self.anchor:
            link={'url':self.anchor['url'],'title':' '.join(self.anchor['parts']), 'rel':self.anchor['rel']}
            self.links.append(link)
            if self.row is not None: self.row['links'].append(link)
            self.anchor=None
        if tag=='tr' and self.row is not None:
            self.row['text']=' '.join(self.row['text']); self.rows.append(self.row); self.row=None

    def listings(self):
        path=urlsplit(self.url).path.rstrip('/')
        berkeley=urlsplit(self.url).hostname=='berkeleyca.gov' and path=='/doing-business/working-city/bid-proposal-opportunities'
        candidates=[]
        for row in self.rows:
            links=[l for l in row['links'] if l['title'] and canonical(l['url'])!=canonical(self.url)]
            if not links: continue
            first=links[0]
            if berkeley and not urlsplit(first['url']).path.startswith(path+'/'): continue
            if not berkeley and not self.rfp_table and not re.search(r'\b(rfp|rfq|bid|solicitation|proposal)\b|\d{1,2}/\d{1,2}/\d{4}',row['text'],re.I): continue
            dates=re.findall(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b',row['text'])
            deadline=f'{dates[0][2]}-{int(dates[0][0]):02}-{int(dates[0][1]):02}' if (berkeley or self.rfp_table) and dates else ''
            candidates.append(dict(first,excerpt=row['text'],deadline=deadline))
        if not candidates and not berkeley:
            for link in self.links:
                if re.search(r'\b(?:RFP|RFQ|solicitation)\s*[#:\d-]',link['title'],re.I):
                    candidates.append(dict(link,excerpt=link['title'],deadline=''))
        unique={c['url']:c for c in candidates}
        next_pages=[l['url'] for l in self.links if ('next' in l['rel'].split() or re.fullmatch(r'(?:next(?: page)?\s*[›»→]?|[›»])',l['title'],re.I)) and urlsplit(l['url']).netloc==urlsplit(self.url).netloc]
        return list(unique.values()),next_pages,berkeley or self.rfp_table


def rank(title, text, facts, reviewed):
    evidence=[]; company=set()
    for field in FIELDS:
        fact=facts.get(field)
        if fact and fact.get('value'):
            words=tokens(fact['value']); company |= words
            evidence.append((field,words,fact))
    unknowns=['Insurance, eligibility, current staff availability and pricing need verification.']
    if not company:
        return dict(score=None,label='Needs company profile',matches=[],evidence=[],unknowns=unknowns)
    if not reviewed:
        return dict(score=None,label='Awaiting review',matches=[],evidence=[],unknowns=['Source details could not be read.']+unknowns)
    title_words=tokens(title); body_words=tokens(text)
    matched=(title_words|body_words)&company
    # A transparent lexical score, not semantic analysis, compliance, or win probability.
    title_fit=len(title_words&company)/max(1,len(title_words))
    body_fit=min(1,len(body_words&company)/max(1,min(len(company),20)))
    score=round(100*(.65*title_fit+.35*body_fit))
    matches=sorted(matched,key=lambda w:(w not in title_words,w))[:12]
    citations=[dict(field=f,document_id=v.get('document_id'),page=v.get('page'),terms=sorted(w&matched)[:8]) for f,w,v in evidence if w&matched]
    return dict(score=score,label='Strong overlap' if score>=65 else 'Some overlap' if score>=30 else 'Low overlap',matches=matches,evidence=citations,unknowns=unknowns)


def register_opportunities(app, db, sources, browser, fetch_public, store_pdf, event):
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS opportunity_sources(rfp_id TEXT,source_id INTEGER,listing_url TEXT,last_seen REAL,PRIMARY KEY(rfp_id,source_id));
        CREATE TABLE IF NOT EXISTS opportunity_reviews(rfp_id TEXT PRIMARY KEY,body TEXT,reviewed REAL,error TEXT);
        CREATE TABLE IF NOT EXISTS discovered_rfps(rfp_id TEXT PRIMARY KEY,pursued INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS source_scans(source_id INTEGER PRIMARY KEY,checked REAL,status TEXT,detail TEXT,pages INTEGER);
        ''')
    task=None

    def persist(source, item):
        now=time.time()
        with db() as c:
            existing=c.execute('SELECT rfp_id AS id FROM opportunity_sources WHERE listing_url=? AND source_id=?',(item['url'],source['id'])).fetchone()
            if not existing:
                existing=c.execute('SELECT id FROM rfps WHERE url=?',(item['url'],)).fetchone()
            if not existing:
                # Link a saved PDF-based bid to its official detail page without cloning its draft.
                for link in item.get('attachments',[]):
                    existing=c.execute('SELECT id FROM rfps WHERE url=?',(link['url'],)).fetchone()
                    if existing: break
            rid=existing['id'] if existing else uuid.uuid4().hex
            if not existing:
                c.execute('INSERT INTO rfps VALUES (?,?,?,?,?,?,?,?,?)',(rid,item['title'],source['name'],item['url'],'Researching',item.get('deadline',''),'',now,now))
                c.execute('INSERT INTO discovered_rfps VALUES (?,0)',(rid,))
            elif c.execute('SELECT 1 FROM discovered_rfps WHERE rfp_id=? AND pursued=0',(rid,)).fetchone():
                c.execute("UPDATE rfps SET title=?,deadline=CASE WHEN ? != '' THEN ? ELSE deadline END,updated=? WHERE id=?",(item['title'],item.get('deadline',''),item.get('deadline',''),now,rid))
            c.execute('INSERT OR REPLACE INTO opportunity_sources VALUES (?,?,?,?)',(rid,source['id'],item['url'],now))
            old=c.execute('SELECT reviewed FROM opportunity_reviews WHERE rfp_id=?',(rid,)).fetchone()
            if not item.get('error') or not old or not old['reviewed']:
                c.execute('INSERT OR REPLACE INTO opportunity_reviews VALUES (?,?,?,?)',(rid,item.get('text',item['excerpt']),now if not item.get('error') else None,item.get('error','')))
            elif item.get('error'):
                c.execute('UPDATE opportunity_reviews SET error=? WHERE rfp_id=?',(item['error'],rid))
        return rid

    async def read_page(url):
        raw,final=await fetch_public(url)
        if len(raw)>25*1024*1024: raise ValueError('Source exceeds the 25 MB reading limit.')
        if raw.startswith(b'%PDF'): return raw,final,None
        return raw,final,Page(raw.decode('utf-8',errors='replace'),final)

    async def scan_source(source):
        sid=source['id']; pages=0; errors=[]; known=True; seen=set(); queue=[source.get('procurement_url') or source.get('official_url')]
        found={}
        try:
            while queue and pages<100:
                url=queue.pop(0)
                if canonical(url) in seen: continue
                seen.add(canonical(url)); browser.status=f'Reading {source["name"]} opportunities'
                try:
                    raw,final,page=await read_page(url)
                    if page is None: raise ValueError('This source is a PDF; its listing page needs a connector.')
                except Exception as exc:
                    errors.append(f'Listing page could not be read: {getattr(exc,"detail",str(exc))}')
                    continue
                items,following,supported=page.listings(); known=known and supported; pages+=1
                for item in items: found.setdefault(item['url'],item)
                queue.extend(u for u in following if canonical(u) not in seen)
            if queue: errors.append('Pagination limit reached; more listing pages remain.')
            # No match threshold or listing-count cap: keep every candidate from every scanned page.
            for item in found.values():
                browser.status=f'Reviewing {item["title"][:70]}'
                try:
                    raw,final,page=await read_page(item['url'])
                    item['attachments']=([{'url':final,'title':item['title']}] if page is None else [l for l in page.links if urlsplit(l['url']).path.lower().endswith('.pdf')])
                    item['text']=page.text if page else item['excerpt']
                    rid=persist(source,dict(item,error='Review in progress'))
                    attachment_errors=[]
                    for attachment in {l['url']:l for l in item['attachments']}.values():
                        try:
                            pdf,pdfurl=await fetch_public(attachment['url'])
                            saved=await store_pdf(pdf,urlsplit(pdfurl).path.split('/')[-1],rfp_id=rid,source_url=pdfurl,automatic=True)
                            with db() as c: doc=c.execute('SELECT pages,total_pages,last_page FROM documents WHERE id=?',(saved['id'],)).fetchone()
                            item['text']+='\n'+'\n'.join(p['text'] for p in json.loads(doc['pages']))
                            if doc['last_page']<doc['total_pages']: attachment_errors.append('A PDF exceeds the 100-page extraction limit; original retained.')
                        except Exception as exc: attachment_errors.append(f'PDF could not be read ({getattr(exc,"detail",str(exc))}).')
                    if attachment_errors:
                        item['error']=' '.join(attachment_errors)[:1000]
                        errors.append(f'{item["title"]}: {item["error"]}')
                    persist(source,item)
                except Exception as exc:
                    item['error']=str(getattr(exc,'detail',str(exc)))[:300]; persist(source,item)
                    errors.append(f'{item["title"]}: {item["error"]}')
            if not known: errors.append('Generic portal discovery: dynamic tables, filters or registration may hide additional RFPs.')
            status=('Blocked' if not pages else 'Partial') if errors else 'Checked'
            detail=f'{len(found)} listings found across {pages} listing pages.'+(' '+ ' '.join(dict.fromkeys(errors))[:1600] if errors else ' All rows on the public listing were reviewed.')
        except Exception as exc:
            status='Blocked'; detail=str(getattr(exc,'detail',str(exc)))[:1200]
        with db() as c: c.execute('INSERT OR REPLACE INTO source_scans VALUES (?,?,?,?,?)',(sid,time.time(),status,detail,pages))
        event('done' if status=='Checked' else 'attention',f'{source["name"]}: {status.lower()}',detail)

    async def scan_all():
        browser.busy=True
        try:
            with db() as c: ids={r[0] for r in c.execute('SELECT source_id FROM watches')}
            for source in sources:
                if source['id'] in ids:
                    with db() as c: still=c.execute('SELECT 1 FROM watches WHERE source_id=?',(source['id'],)).fetchone()
                    if still: await scan_source(source)
        finally:
            browser.busy=False; browser.status='Opportunity review finished'

    @app.post('/api/opportunities/refresh')
    async def refresh():
        nonlocal task
        if browser.busy or browser.controller!='billy' or browser.pending: raise HTTPException(409,'Hand the browser back to Billy and finish any pending decision before refreshing.')
        if task and not task.done(): raise HTTPException(409,'A source review is already running.')
        with db() as c: count=c.execute('SELECT COUNT(*) FROM watches').fetchone()[0]
        if not count: raise HTTPException(400,'Watch a source first.')
        browser.busy=True
        task=asyncio.create_task(scan_all()); browser.task=task
        return {'started':True}

    @app.get('/api/opportunities')
    async def feed():
        with db() as c:
            rows=[dict(r) for r in c.execute('''SELECT DISTINCT r.*,v.body,v.reviewed,v.error,
                (SELECT COUNT(*) FROM documents WHERE rfp_id=r.id) AS documents,
                COALESCE(d.pursued,1) AS pursued
                FROM rfps r JOIN opportunity_sources s ON s.rfp_id=r.id JOIN watches w ON w.source_id=s.source_id
                LEFT JOIN opportunity_reviews v ON v.rfp_id=r.id LEFT JOIN discovered_rfps d ON d.rfp_id=r.id''')]
            facts={r['field']:dict(r) for r in c.execute('SELECT * FROM company_facts')}
            scans={r['source_id']:dict(r) for r in c.execute('SELECT * FROM source_scans')}
            watching={r[0] for r in c.execute('SELECT source_id FROM watches')}
            associations=[dict(r) for r in c.execute('SELECT * FROM opportunity_sources')]
        for row in rows:
            row['fit']=rank(row['title'],row.pop('body') or '',facts,row['reviewed'])
            row['sources']=[s for s in associations if s['rfp_id']==row['id'] and s['source_id'] in watching]
        rows.sort(key=lambda r:-(r['fit']['score'] if r['fit']['score'] is not None else -1))
        return {'rows':rows,'scanning':bool(task and not task.done()),'sources':[dict(id=s['id'],name=s['name'],**{k:v for k,v in scans.get(s['id'],{}).items() if k!='source_id'}) for s in sources if s['id'] in watching], 'method':'Preliminary keyword fit against company capabilities. Not a compliance check or win probability.'}

    @app.post('/api/opportunities/{rfp_id}/pursue')
    async def pursue(rfp_id:str):
        with db() as c:
            if not c.execute('SELECT 1 FROM rfps WHERE id=?',(rfp_id,)).fetchone(): raise HTTPException(404,'RFP not found')
            c.execute('UPDATE discovered_rfps SET pursued=1 WHERE rfp_id=?',(rfp_id,))
        return {'id':rfp_id,'pursued':True}

    return feed,refresh,persist,scan_source
