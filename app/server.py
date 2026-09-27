"""Billy's single-owner research workspace. Bind to loopback, never the public web."""
import asyncio
import base64
import io
import hashlib
import http.client
import ssl
from datetime import date
import ipaddress
import json
import logging
import os
from pathlib import Path
import socket
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse, urljoin, unquote

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(globals().get('_workspace_data') or os.environ.get('BILLY_DATA_DIR', ROOT / '.billy'))
DATA.mkdir(parents=True, exist_ok=True)
SOURCE_FILE = Path(os.environ.get('BILLY_SOURCES', ROOT / 'rfpsonar-found-rfp-sources.json'))
SOURCES = globals().get('_workspace_sources')
if SOURCES is None: SOURCES = json.loads(SOURCE_FILE.read_text()) if SOURCE_FILE.exists() else []
DB = DATA / 'workspace.sqlite3'
CATALOG_DB = Path(globals().get('_workspace_catalog') or DATA / 'catalog.sqlite3')

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def catalog_db():
    c=sqlite3.connect(CATALOG_DB,factory=ClosingConnection)
    c.row_factory=sqlite3.Row
    return c
WATCH_LIMIT = int(os.environ.get('BILLY_WATCH_LIMIT', '10'))
ENVIRONMENT = os.environ.get('BILLY_ENVIRONMENT', 'This Mac')
ALLOWED_ORIGINS = set(os.environ.get('BILLY_ORIGINS', 'http://localhost:8080,http://127.0.0.1:8080,http://localhost:8081,http://127.0.0.1:8081').split(','))
# Hosts the private API answers to: loopback, plus an authenticated reverse proxy hostname
# (NetBird) whose proxy performs the login before traffic reaches this loopback listener.
ALLOWED_HOSTS = {'localhost', '127.0.0.1', 'testserver'} | {h.strip().lower() for h in os.environ.get('BILLY_PUBLIC_HOSTS', '').split(',') if h.strip()}

def db():
    c = sqlite3.connect(DB,factory=ClosingConnection)
    c.row_factory = sqlite3.Row
    return c

with db() as c:
    c.executescript('''CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at REAL, kind TEXT, title TEXT, detail TEXT);
    CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, name TEXT, first_page INTEGER, last_page INTEGER, added REAL, pages TEXT);
    CREATE TABLE IF NOT EXISTS checks(source_id INTEGER PRIMARY KEY, checked REAL, url TEXT, title TEXT);
    CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS watches(source_id INTEGER PRIMARY KEY, added REAL);
    CREATE TABLE IF NOT EXISTS rfps(id TEXT PRIMARY KEY, title TEXT, agency TEXT, url TEXT, status TEXT, deadline TEXT, notes TEXT, created REAL, updated REAL);''')
    columns = {r['name'] for r in c.execute('PRAGMA table_info(documents)')}
    for name, definition in {'rfp_id':'TEXT', 'source_url':'TEXT', 'sha256':'TEXT', 'total_pages':'INTEGER', 'media_type':"TEXT DEFAULT 'application/pdf'", 'file_ext':"TEXT DEFAULT '.pdf'", 'extraction_note':"TEXT DEFAULT ''"}.items():
        if name not in columns: c.execute(f'ALTER TABLE documents ADD COLUMN {name} {definition}')

def save(key, value):
    with db() as c:
        c.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(value)))

def read(key, default=None):
    with db() as c:
        row = c.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    return json.loads(row['value']) if row else default

def event(kind, title, detail=''):
    with db() as c:
        c.execute('INSERT INTO events(at,kind,title,detail) VALUES (?,?,?,?)', (time.time(), kind, title, detail))

async def public_addresses(url):
    """Reject local services, credentials, unusual ports and non-HTTP schemes."""
    try:
        p = urlparse(url)
        if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password or p.port not in (None,80,443):
            raise ValueError()
        host = p.hostname.lower().rstrip('.')
        if host == 'localhost' or host.endswith(('.localhost','.local','.internal')):
            raise ValueError()
        addresses = await asyncio.get_running_loop().getaddrinfo(host, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError()
        return [a[4][0] for a in addresses]
    except (ValueError, OSError):
        raise HTTPException(400, 'Only public HTTP(S) pages on standard ports are available in Billy’s browser.')

async def public_url(url):
    await public_addresses(url)
    return url

class Browser:
    def __init__(self):
        self.pw = self.browser = self.page = None
        self.lock = asyncio.Lock()
        self.controller = 'billy'
        self.busy = False
        self.status = 'Ready for a source'
        self.pending = None
        self.allowed_write = None
        self.image = None
        self.task = None
        self.verified_hosts = {}
        self.error = None
        self.action_at = 0
        self.touring = False
        self.stop_tour = False
        self.tour_failures = {}

    async def start(self):
        if self.page and not self.page.is_closed(): return
        self.pw = await async_playwright().start()
        try:
            self.browser = await self.pw.chromium.launch(headless=True, chromium_sandbox=True, args=['--disable-dev-shm-usage','--disable-background-networking'])
        except Exception:
            await self.pw.stop()
            self.pw = None
            raise RuntimeError('The browser could not start. Its runtime needs attention; your saved work is retained.')
        context = await self.browser.new_context(viewport={'width':1280,'height':800}, accept_downloads=False, service_workers='block')
        await context.route('**/*', self.route)
        await context.route_web_socket('**/*', lambda ws: ws.close())
        await context.expose_binding('billyRequestFormApproval', self.form_approval)
        await context.add_init_script("""document.addEventListener('submit', event => {
            if (window.__billySubmitOnce) { window.__billySubmitOnce = false; return; }
            event.preventDefault(); event.stopImmediatePropagation();
            const form = event.target, submitter = event.submitter;
            window.__billyResumeForm = () => {
                window.__billySubmitOnce = true;
                form.requestSubmit(submitter || undefined);
            };
            window.billyRequestFormApproval({url: form.action || location.href,
                method: (form.method || 'GET').toUpperCase()});
        }, true);""")
        self.page = await context.new_page()
        self.page.on('dialog', lambda dialog: dialog.dismiss())
        context.on('page', lambda page: asyncio.create_task(page.close()) if self.page and page != self.page else None)

    async def form_approval(self, source, form):
        self.pending = {'id': uuid.uuid4().hex, 'kind':'form',
            'title':'Submit this form?',
            'detail':'The form is filled, but has not been submitted. Review the browser before approving.',
            'url':str(form.get('url',''))[:2000], 'method':str(form.get('method','GET'))[:10]}
        event('decision','Form submission paused','Waiting for explicit approval.')

    async def route(self, route):
        req = route.request
        try:
            host = urlparse(req.url).netloc
            if self.verified_hosts.get(host, 0) < time.time()-30:
                await public_url(req.url)
                self.verified_hosts[host] = time.time()
            elif urlparse(req.url).scheme not in ('http','https'):
                raise ValueError()
            if req.method not in ('GET','HEAD','OPTIONS'):
                signature = (req.method, req.url)
                if self.allowed_write and self.allowed_write[:2] == signature and self.allowed_write[2] > time.time():
                    self.allowed_write = None
                else:
                    same_site = self.page and urlparse(req.url).hostname == urlparse(self.page.url).hostname
                    recent_action = time.time() - self.action_at < 4
                    if self.controller != 'you' or not same_site or not recent_action or self.pending:
                        await route.abort()
                        return
                    self.pending = {'id':uuid.uuid4().hex,'kind':'submission','title':'Approve this network action?', 'detail':f'{req.method} to {urlparse(req.url).hostname}. Billy paused it. Approve once, then repeat the action in the browser.', 'url': req.url, 'method':req.method}
                    event('decision', 'A site action needs approval', f'{req.method} {urlparse(req.url).hostname}')
                    await route.abort()
                    return
            await route.continue_()
        except Exception:
            await route.abort()

    async def yield_tour(self, seconds=12):
        """Ask a running source tour to stop and wait for the browser to free up."""
        if not self.touring: return
        self.stop_tour = True
        deadline = time.time() + seconds
        while self.busy and time.time() < deadline: await asyncio.sleep(0.2)

    async def tour(self, url, source_id, name):
        """Review a watched agency's listing page in the real browser, scrolling slowly so the work
        is visible in Activity. Reads and saves the page like research(); a portal that will not
        load is noted quietly and skipped for an hour, never turned into an attention state."""
        self.busy = True; self.touring = True; self.stop_tour = False; self.error = None
        self.status = f'Reviewing {name} opportunities'
        started = time.time()
        event('working', f'Reviewing {name} listings', url)
        try:
            async with self.lock:
                await self.start()
                self.verified_hosts.clear()
                response = await self.page.goto(url, wait_until='domcontentloaded', timeout=35000)
                await self.page.wait_for_timeout(800)
                await self.capture()
                if response and response.status >= 400: raise RuntimeError(f'The portal returned HTTP {response.status}.')
                height = await self.page.evaluate('document.documentElement.scrollHeight')
                position = 0
                for _ in range(12):
                    if self.stop_tour: break
                    await self.page.mouse.wheel(0, 450); position += 450
                    await self.page.wait_for_timeout(900)
                    await self.capture()
                    if position >= height - 800: break
                text = await self.page.locator('body').inner_text(timeout=8000)
                title = await self.page.title()
                links = await self.page.locator('a[href]').evaluate_all("els => els.map(a=>({title:a.innerText.trim(),url:a.href})).filter(a=>a.title && /^https?:/.test(a.url))")
                unique = {}
                for link in links:
                    if any(word in (link['title']+' '+link['url']).lower() for word in ('rfp','proposal','solicitation','bid')):
                        unique.setdefault(link['url'], {'title':link['title'][:200], 'url':link['url']})
                save('research', {'url':self.page.url,'title':title,'text':text[:50000],'links':list(unique.values())[:30],'checked':time.time(),'seconds':round(time.time()-started,1),'source_id':source_id})
                with db() as c: c.execute('INSERT OR REPLACE INTO checks VALUES (?,?,?,?)', (source_id, time.time(), self.page.url, title))
                self.status = 'Ready for a source'
                event('done', f'Reviewed {name} listings', f'{title} · {len(unique)} opportunity links · {round(time.time()-started,1)}s')
                return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.tour_failures[source_id] = time.time()
            self.status = 'Ready for a source'
            event('working', f'{name} did not load in Billy’s browser', str(exc)[:200] + ' Skipping it this round.')
            await self.capture()
            return False
        finally:
            self.busy = False; self.touring = False; self.stop_tour = False

    async def capture(self):
        if not self.page: return
        try: self.image = await self.page.screenshot(type='jpeg', quality=65, timeout=4000, animations='disabled')
        except Exception: pass

    async def research(self, url, source_id=None, company=False):
        self.busy = True
        self.error = None
        self.status = 'Opening the source'
        started = time.time()
        event('working', 'Opening a real browser', url)
        try:
            async with self.lock:
                await self.start()
                self.verified_hosts.clear()
                response = await self.page.goto(url, wait_until='domcontentloaded', timeout=35000)
                await self.page.wait_for_timeout(800)
                await self.capture()
                if response and response.status >= 400: raise RuntimeError(f'The portal returned HTTP {response.status}. You can inspect it or try again.')
                self.status = 'Reading the page'
                text = await self.page.locator('body').inner_text(timeout=8000)
                title = await self.page.title()
                links = await self.page.locator('a[href]').evaluate_all("els => els.map(a=>({title:a.innerText.trim(),url:a.href})).filter(a=>a.title && /^https?:/.test(a.url))")
                unique = {}
                for link in links:
                    if company or any(word in (link['title']+' '+link['url']).lower() for word in ('rfp','proposal','environmental','solicitation','bid')):
                        unique.setdefault(link['url'], {'title':link['title'][:200], 'url':link['url']})
                result = {'url':self.page.url,'title':title,'text':text[:50000],'links':list(unique.values())[:80 if company else 30],'checked':time.time(),'seconds':round(time.time()-started,1),'source_id':source_id}
                save('research', result)
                if source_id:
                    with db() as c: c.execute('INSERT OR REPLACE INTO checks VALUES (?,?,?,?)', (source_id,time.time(),self.page.url,title))
                self.status = 'Ready for your next decision'
                event('done', 'Page read and saved', f'{title} · {len(text):,} characters · {result["seconds"]}s')
                return result
        except Exception as exc:
            logging.exception('Research failed')
            self.error = str(exc)[:450]
            self.status = 'Needs your attention'
            event('error', 'Could not finish reading this page', self.error)
            await self.capture()
        finally:
            self.busy = False

b = Browser()
document_jobs = 0

@asynccontextmanager
async def document_work():
    global document_jobs
    document_jobs += 1
    try:
        yield
    finally:
        document_jobs -= 1


@asynccontextmanager
async def lifespan(app):
    watcher = asyncio.create_task(watch_opportunities())
    tour = asyncio.create_task(tour_sources())
    yield
    await agent.close()
    watcher.cancel(); tour.cancel()
    await asyncio.gather(watcher, tour, return_exceptions=True)
    if b.task and not b.task.done():
        b.task.cancel()
        await asyncio.gather(b.task, return_exceptions=True)
    if b.browser: await b.browser.close()
    if b.pw: await b.pw.stop()

app = FastAPI(lifespan=lifespan)

@app.middleware('http')
async def local_access(request: Request, call_next):
    # This service is reached locally or through an SSH tunnel, not public nginx.
    host = request.headers.get('host','').split(':')[0].lower()
    if host not in ALLOWED_HOSTS:
        return Response('Use the local workspace connection.', status_code=403)
    origin = request.headers.get('origin')
    if origin and origin not in ALLOWED_ORIGINS:
        return Response('Origin not allowed', status_code=403)
    if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-billy-client') != 'workspace':
        return Response('Workspace request header required', status_code=403)
    if request.method == 'OPTIONS':
        response = Response(status_code=204)
    else:
        response = await call_next(request)
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Vary'] = 'Origin'
        response.headers['Access-Control-Allow-Headers'] = 'content-type,x-billy-client'
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith(('/api/', '/w/')) else 'no-cache'
    return response

@app.get('/api/state')
async def state():
    with db() as c:
        events = [dict(r) for r in c.execute('SELECT * FROM events ORDER BY id DESC LIMIT 24')]
        docs = [dict(r) for r in c.execute('SELECT id,name,first_page,last_page,added,rfp_id,source_url,total_pages,media_type,extraction_note FROM documents ORDER BY added DESC')]
    return {'environment':ENVIRONMENT,'document_jobs':document_jobs,'browser':{'ready':bool(b.page),'url':b.page.url if b.page else None,'controller':b.controller,'busy':b.busy,'status':b.status,'error':b.error,'pending':b.pending},'events':events,'documents':docs,'research':read('research'),'total':len(SOURCES),'policy':{'draft_forms':True,'submission':'approval_required'},'model':None}

@app.get('/api/sources')
async def sources(q: str='', state: str='', offset: int=0, limit: int=30, watched: bool=False):
    if offset < 0 or not 1 <= limit <= 100: raise HTTPException(400, 'Invalid page')
    selected_states = {code.strip().upper() for code in state.split(',') if code.strip()}
    with db() as c: watching={r['source_id'] for r in c.execute('SELECT source_id FROM watches')}
    rows = [r for r in SOURCES if (not watched or r['id'] in watching) and (not selected_states or r.get('state_code') in selected_states) and (not q or q.lower() in (r.get('name','')+' '+r.get('state_code','')).lower())]
    with db() as c: checks={r['source_id']:r['checked'] for r in c.execute('SELECT source_id,checked FROM checks')}
    return {'total':len(rows),'indexed':len(SOURCES),'watch_count':len(watching),'watch_limit':WATCH_LIMIT,'states':sorted(set(r.get('state_code','') for r in SOURCES)), 'rows':[dict(id=r['id'],name=r['name'],state=r.get('state_code'),url=r.get('procurement_url') or r.get('official_url'),checked=checks.get(r['id']),watched=r['id'] in watching) for r in rows[offset:offset+limit]]}

class WatchRequest(BaseModel):
    watched: bool

@app.post('/api/sources/{source_id}/watch')
async def watch_source(source_id: int, req: WatchRequest):
    row=next((r for r in SOURCES if r['id']==source_id),None)
    if not row: raise HTTPException(404,'Source not found')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=c.execute('SELECT 1 FROM watches WHERE source_id=?',(source_id,)).fetchone()
        count=c.execute('SELECT COUNT(*) FROM watches').fetchone()[0]
        if req.watched and not existing:
            if count>=WATCH_LIMIT: raise HTTPException(409,f'Your workspace allows {WATCH_LIMIT} watched sources. Unwatch one before adding another.')
            c.execute('INSERT INTO watches VALUES (?,?)',(source_id,time.time()))
        elif not req.watched:
            c.execute('DELETE FROM watches WHERE source_id=?',(source_id,))
    return {'watched':req.watched}

class ResearchRequest(BaseModel):
    source_id: int | None = None
    url: str | None = None

@app.post('/api/research')
async def research(req: ResearchRequest):
    if b.busy: raise HTTPException(409, 'Billy is already reading a page.')
    if b.controller=='you': raise HTTPException(409, 'Hand the browser back to Billy first.')
    await b.yield_tour()
    if req.source_id is not None:
        row = next((r for r in SOURCES if r['id']==req.source_id), None)
        if not row: raise HTTPException(404, 'Source not found')
        url = row.get('procurement_url') or row.get('official_url')
    else:
        result = read('research',{}) or {}
        allowed = {r['url'] for r in result.get('links',[])} | {result.get('url')}
        if req.url not in allowed: raise HTTPException(400, 'Choose a link from the saved page.')
        url = req.url
    await public_url(url)
    # URL validation yields; a scheduled source check may have claimed the session.
    if b.busy or b.controller != 'billy' or b.pending:
        raise HTTPException(409, 'Billy’s session is busy or waiting for your decision.')
    b.busy = True
    b.task = asyncio.create_task(b.research(url,req.source_id))
    return {'started':True}

@app.get('/api/browser/frame')
async def frame():
    if b.page:
        if b.busy: await b.capture()
        else:
            async with b.lock: await b.capture()
    if not b.image: return Response(status_code=204)
    return Response(b.image,media_type='image/jpeg')

class ControlRequest(BaseModel):
    controller: str

@app.post('/api/browser/control')
async def control(req: ControlRequest):
    if req.controller not in ('you','billy'): raise HTTPException(400,'Unknown controller')
    if b.busy: raise HTTPException(409,'Wait for the current page read to finish.')
    b.controller = req.controller
    event('control', 'You took control' if req.controller=='you' else 'Browser handed back to Billy')
    return {'controller':b.controller}

class BrowserAction(BaseModel):
    kind: str
    x: float=Field(default=0,ge=0,le=1280)
    y: float=Field(default=0,ge=0,le=800)
    text: str=Field(default='',max_length=10000)
    delta: int=Field(default=0,ge=-2000,le=2000)

@app.post('/api/browser/action')
async def action(req: BrowserAction):
    if b.controller!='you' or b.busy or not b.page: raise HTTPException(409,'Take control of the ready browser first.')
    async with b.lock:
        b.action_at = time.time()
        if req.kind=='click': await b.page.mouse.click(req.x,req.y)
        elif req.kind=='type': await b.page.keyboard.insert_text(req.text)
        elif req.kind=='key' and req.text in ('Enter','Tab','Backspace','Escape','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','ControlOrMeta+A'):
            await b.page.keyboard.press(req.text)
        elif req.kind=='scroll': await b.page.mouse.wheel(0,req.delta)
        elif req.kind=='back': await b.page.go_back(wait_until='domcontentloaded',timeout=15000)
        elif req.kind=='reload': await b.page.reload(wait_until='domcontentloaded',timeout=15000)
        else: raise HTTPException(400,'Unknown browser action')
        await b.capture()
    return {'ok':True}

class Approval(BaseModel):
    id: str
    approved: bool

@app.post('/api/browser/approval')
async def approval(req: Approval):
    pending = b.pending
    if not pending or pending['id']!=req.id: raise HTTPException(409,'This request is no longer pending.')
    if req.approved:
        await public_url(pending['url'])
        b.allowed_write=(pending['method'],pending['url'],time.time()+30)
        if pending['kind']=='form':
            await b.page.evaluate('() => window.__billyResumeForm?.()')
    elif pending['kind']=='form' and b.page:
        await b.page.evaluate('() => { window.__billyResumeForm = null; }')
    b.pending=None
    event('approval','Network action approved once' if req.approved else 'Network action declined', 'Repeat the intended action within 30 seconds.' if req.approved else '')
    return {'ok':True}

STATUSES = ('Researching','Drafting','Ready for review','Responded','Closed — won','Closed — lost','Not pursuing')

class RFPInput(BaseModel):
    title: str = Field(min_length=1,max_length=300)
    agency: str = Field(default='',max_length=200)
    url: str = Field(default='',max_length=2000)
    status: str = 'Researching'
    deadline: str = ''
    notes: str = Field(default='',max_length=10000)


def require_rfp(rfp_id):
    with db() as c: row=c.execute('SELECT * FROM rfps WHERE id=?',(rfp_id,)).fetchone()
    if not row: raise HTTPException(404,'RFP not found')
    return dict(row)

async def validate_rfp(req):
    if not req.title.strip(): raise HTTPException(400,'Give this RFP a title.')
    if req.status not in STATUSES: raise HTTPException(400,'Unknown RFP status')
    if req.deadline:
        try: date.fromisoformat(req.deadline)
        except ValueError: raise HTTPException(400,'Use a valid deadline date.')
    if req.url: await public_url(req.url)

@app.get('/api/rfps')
async def rfps():
    with db() as c:
        rows=[dict(r) for r in c.execute('SELECT rfps.*, (SELECT COUNT(*) FROM documents WHERE rfp_id=rfps.id) AS documents FROM rfps WHERE NOT EXISTS (SELECT 1 FROM discovered_rfps d WHERE d.rfp_id=rfps.id AND d.pursued=0) ORDER BY updated DESC')]
    return {'rows':rows,'statuses':STATUSES}

@app.post('/api/rfps')
async def create_rfp(req: RFPInput):
    await validate_rfp(req)
    rfp_id=uuid.uuid4().hex; now=time.time()
    with db() as c:
        c.execute('INSERT INTO rfps VALUES (?,?,?,?,?,?,?,?,?)',(rfp_id,req.title.strip(),req.agency,req.url,req.status,req.deadline,req.notes,now,now))
    event('done','RFP added to your pipeline',req.title)
    return require_rfp(rfp_id)

@app.post('/api/rfps/{rfp_id}')
async def update_rfp(rfp_id: str, req: RFPInput):
    old=require_rfp(rfp_id)
    await validate_rfp(req)
    with db() as c:
        c.execute('UPDATE rfps SET title=?,agency=?,url=?,status=?,deadline=?,notes=?,updated=? WHERE id=?',(req.title.strip(),req.agency,req.url,req.status,req.deadline,req.notes,time.time(),rfp_id))
    if old['status']!=req.status: event('status',f'RFP marked {req.status}',req.title)
    return require_rfp(rfp_id)

async def store_pdf(raw, name, first_page=1, last_page=0, rfp_id=None, source_url=None, automatic=False):
    if rfp_id: require_rfp(rfp_id)
    if len(raw)>25*1024*1024: raise HTTPException(413,'Choose a PDF smaller than 25 MB.')
    if not raw.startswith(b'%PDF'): raise HTTPException(400,'This source did not return a PDF document.')
    digest=hashlib.sha256(raw).hexdigest()
    def extract():
        reader=PdfReader(io.BytesIO(raw)); total=len(reader.pages)
        end=last_page or (min(total,100) if automatic else total)
        if first_page<1 or end<first_page or end>total or end-first_page>99:
            raise ValueError('Choose up to 100 pages within the PDF.')
        # 50,000 characters keeps any single page inside the agent's per-call result limit.
        pages=[{'page':i+1,'text':(reader.pages[i].extract_text() or '')[:50000]} for i in range(first_page-1,end)]
        return end,pages,total
    try: end,pages,total=await asyncio.wait_for(asyncio.to_thread(extract),timeout=40)
    except Exception: raise HTTPException(400,'Could not read this PDF. Check that it is unlocked and the selected range contains at most 100 pages.')
    with db() as c:
        duplicate=c.execute('SELECT id,first_page,last_page FROM documents WHERE sha256=? AND rfp_id IS ? AND first_page=? AND last_page=?',(digest,rfp_id,first_page,end)).fetchone()
    if duplicate: return {'id':duplicate['id'],'pages':end-first_page+1,'existing':True}
    doc_id=uuid.uuid4().hex
    path=DATA / f'{doc_id}.pdf'
    path.write_bytes(raw)
    try:
        with db() as c:
            c.execute('INSERT INTO documents(id,name,first_page,last_page,added,pages,rfp_id,source_url,sha256,total_pages) VALUES (?,?,?,?,?,?,?,?,?,?)',(doc_id,Path(name).name[:200],first_page,end,time.time(),json.dumps(pages),rfp_id,source_url,digest,total))
            if rfp_id: c.execute('UPDATE rfps SET updated=? WHERE id=?',(time.time(),rfp_id))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    event('done','RFP original saved' if rfp_id else 'Previous response imported',f'{name} · PDF pages {first_page}–{end}. Complete original retained.')
    return {'id':doc_id,'pages':len(pages),'existing':False}

@app.post('/api/documents')
async def document(file: UploadFile=File(...), first_page: int=Form(1), last_page: int=Form(0), rfp_id: str=Form('')):
    async with document_work():
        raw = await file.read(25*1024*1024+1)
        return await store_pdf(raw,file.filename or 'proposal.pdf',first_page,last_page,rfp_id or None)

class PDFSource(BaseModel):
    url: str = Field(max_length=2000)

def fetch_pinned(url, address):
    p=urlparse(url); port=p.port or (443 if p.scheme=='https' else 80)
    # Connect to the vetted numeric address; preserve the original Host and TLS SNI.
    conn=http.client.HTTPConnection(p.hostname,port,timeout=15)
    try:
        conn.sock=socket.create_connection((address,port),timeout=15)
        if p.scheme=='https':
            conn.sock=ssl.create_default_context().wrap_socket(conn.sock,server_hostname=p.hostname)
        path=p.path or '/'
        if p.query: path+='?'+p.query
        conn.request('GET',path,headers={'User-Agent':'Billy-RFP-Research/1.0','Host':p.netloc})
        response=conn.getresponse()
        if response.status in (301,302,303,307,308) and response.getheader('Location'):
            return None,urljoin(url,response.getheader('Location'))
        if response.status>=400: raise HTTPException(400,f'The source returned HTTP {response.status}. Upload the original if you already have it.')
        if int(response.getheader('Content-Length','0'))>25*1024*1024:
            raise HTTPException(413,'Choose a PDF smaller than 25 MB.')
        return response.read(25*1024*1024+1),None
    finally: conn.close()

async def fetch_pdf(url):
    # Revalidate every redirect and never forward browser cookies or credentials.
    for _ in range(6):
        addresses=await public_addresses(url)
        try: raw,redirect=await asyncio.wait_for(asyncio.to_thread(fetch_pinned,url,addresses[0]),timeout=25)
        except HTTPException: raise
        except Exception: raise HTTPException(400,'Could not download this source. Try uploading the original PDF.')
        if not redirect: return raw,url
        url=redirect
    raise HTTPException(400,'The source redirected too many times.')

@app.post('/api/rfps/{rfp_id}/documents/download')
async def download_pdf(rfp_id: str, req: PDFSource):
    require_rfp(rfp_id)
    async with document_work():
        raw,url=await fetch_pdf(req.url)
        name=Path(unquote(urlparse(url).path)).name or 'rfp-original.pdf'
        return await store_pdf(raw,name,rfp_id=rfp_id,source_url=url,automatic=True)

@app.get('/api/documents/{doc_id}')
async def get_document(doc_id: str):
    with db() as c: row=c.execute('SELECT * FROM documents WHERE id=?',(doc_id,)).fetchone()
    if not row: raise HTTPException(404,'Document not found')
    result=dict(row); result['pages']=json.loads(result['pages']);return result

from app.document_previews import register_document_previews
document_preview = register_document_previews(app, db, DATA)
from app.company_attachments import register_company_attachments
company_attachment, original_document = register_company_attachments(app, db, DATA, store_pdf, event, document_work)

from app.company import register_company
company_profile, company_edit, company_evidence, company_task = register_company(app, db, event)

from app.rfp_workspace import register_rfp_workspace
rfp_workspace, save_response_section, add_response_note = register_rfp_workspace(app, db, require_rfp, event)

from app.discussion import register_discussion
discuss, discussion_config, transcribe = register_discussion(app, db, require_rfp)

from app.voice import register_voice
voice_config, voice_token, voice_settings, voice_sample = register_voice(app, event, read, save, DATA)

from app.opportunity_imports import register_imports
import_batches, import_opportunities, import_visibility, sync_catalog = register_imports(app, db, catalog_db)

from app.opportunities import register_opportunities
opportunity_feed, refresh_opportunities, persist_opportunity, scan_opportunity_source = register_opportunities(app, db, SOURCES, b, fetch_pdf, store_pdf, event, sync_catalog)

from app.agent import BillyAgent
from app.response_pdf import register_response_pdf
export_response_pdf = register_response_pdf(app, db, DATA, rfp_workspace, event)
from app.company_web import CompanyWebsite
company_website = CompanyWebsite(db, b, public_url, event)
from app.rfp_research import RFPResearch
rfp_research = RFPResearch(db, DATA, fetch_pdf, store_pdf, require_rfp, event)
from app.response_review import register_response_review
response_review = register_response_review(app, db, rfp_workspace, DATA)
agent = BillyAgent(app, db, event, company_profile, opportunity_feed, rfp_workspace, save_response_section, research, b, export_response_pdf, usage_db=globals().get('_workspace_usage_db'), company_website=company_website,rfp_research=rfp_research,review=response_review)

TOUR_CYCLE_SECONDS = 900
tour_state = {'requested': 0.0, 'cycle_done': 0.0, 'cursor': 0}

class TourRequest(BaseModel):
    pass

@app.post('/api/tour')
async def request_tour(req: TourRequest = TourRequest()):
    """The app asks for a fresh review of the watched listings; the scheduler runs it when idle."""
    tour_state['requested'] = time.time()
    with db() as c: count = c.execute('SELECT COUNT(*) FROM watches').fetchone()[0]
    return {'watched': count, 'touring': b.touring}

async def tour_step():
    """One scheduling decision: review the next watched source in the browser if nothing else needs it.
    A cycle runs when the app requested one, or every TOUR_CYCLE_SECONDS while idle. Returns the source toured."""
    if b.busy or b.controller != 'billy' or b.pending: return None
    if agent.task and not agent.task.done(): return None
    now = time.time()
    if now - tour_state['cycle_done'] < TOUR_CYCLE_SECONDS and tour_state['requested'] <= tour_state['cycle_done']: return None
    with db() as c: watched = {r['source_id'] for r in c.execute('SELECT source_id FROM watches')}
    candidates = [s for s in SOURCES if s['id'] in watched and now - b.tour_failures.get(s['id'], 0) > 3600]
    if not candidates:
        tour_state['cycle_done'] = now
        return None
    source = candidates[tour_state['cursor'] % len(candidates)]
    tour_state['cursor'] += 1
    await b.tour(source.get('procurement_url') or source.get('official_url'), source['id'], source['name'])
    if tour_state['cursor'] % len(candidates) == 0: tour_state['cycle_done'] = time.time()
    return source

async def tour_sources():
    while True:
        await asyncio.sleep(3)
        try: await tour_step()
        except asyncio.CancelledError: raise
        except Exception: logging.exception('Source tour failed')

async def watch_opportunities():
    while True:
        await asyncio.sleep(15)
        if b.busy or b.controller != 'billy' or b.pending: continue
        with db() as c:
            due=c.execute('SELECT 1 FROM watches w LEFT JOIN source_scans s ON s.source_id=w.source_id WHERE s.checked IS NULL OR s.checked<? LIMIT 1',(time.time()-3600,)).fetchone()
        if due:
            try: await refresh_opportunities()
            except HTTPException: pass

app.mount('/', StaticFiles(directory=ROOT/'site',html=True),name='site')

# Each company gets its own runtime (including agent/browser), database and files.
# The directory mounts these runtimes; it never changes an in-flight job's DB.
if __name__ == 'app.server':
    import sys
    from app.workspaces import WorkspaceDirectory
    workspace_directory = WorkspaceDirectory(sys.modules[__name__])
    app = workspace_directory.app
