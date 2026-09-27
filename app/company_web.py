"""Company-site research in the workspace's browser, with saved quotation evidence."""
import asyncio
import json
import re
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException


def website_url(value):
    value = str(value or '').strip()
    if not value:
        return ''
    if '://' not in value:
        value = 'https://' + value
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.port not in (None, 80, 443) or any(c.isspace() for c in value):
        raise ValueError('Provide a public company website URL.')
    return urlunsplit((p.scheme, p.netloc.lower(), p.path or '/', p.query, ''))


def site_host(url):
    return (urlsplit(url).hostname or '').lower().removeprefix('www.')


class CompanyWebsite:
    def __init__(self, db, browser, public_url, event):
        self.db, self.browser = db, browser
        self.public_url, self.event = public_url, event

    async def read(self, run_id, url=None):
        with self.db() as c:
            fact = c.execute("SELECT value FROM company_facts WHERE field='company.website'").fetchone()
            message = c.execute("SELECT text,created FROM agent_messages WHERE run_id=? AND role='user' ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
            if message and c.execute('SELECT count(*) FROM company_web_pages WHERE run_id=? AND checked>=?', (run_id,message['created'])).fetchone()[0] >= 4:
                raise ValueError('Four company pages have been read this turn. Save the supported profile facts and summarize them now.')
            pages = c.execute('SELECT links FROM company_web_pages WHERE run_id=?', (run_id,)).fetchall()
        roots = []
        if fact:
            try: roots.append(website_url(fact['value']))
            except ValueError: pass
        # Only the current user's message may introduce a new website.
        for found in re.findall(r'(?<![\w@/])(?:https?://[^\s<>"\']+|www\.[^\s<>"\']+|(?:[a-zA-Z0-9][a-zA-Z0-9-]*\.)+[a-zA-Z]{2,24}(?:/[^\s<>"\']*)?)', message['text'] if message else ''):
            try: roots.insert(0, website_url(found.rstrip('.,;!?)')))
            except ValueError: pass
        if not roots:
            raise ValueError('Ask for the company website URL first.')
        target = website_url(url or roots[0])
        links = {website_url(link['url']) for page in pages for link in json.loads(page['links'])}
        if target not in roots and (target not in links or site_host(target) not in {site_host(root) for root in roots}):
            raise ValueError('Use the saved company website, a URL supplied by the user, or a same-site link returned by this tool.')
        await self.public_url(target)
        b = self.browser
        if getattr(b, 'touring', False): await b.yield_tour()
        if b.busy or b.controller != 'billy' or b.pending:
            raise HTTPException(409, 'Hand the browser back to Billy or finish its current task first.')
        b.busy = True
        b.task = asyncio.create_task(b.research(target, company=True))
        captured = await b.task
        if b.error:
            raise ValueError('Could not read the company website. ' + b.error)
        if not isinstance(captured, dict):
            raise ValueError('The company page could not be captured. Try again.')
        if site_host(captured.get('url', '')) != site_host(target):
            raise ValueError('The website redirected to a different domain. Ask the user to confirm its company URL.')
        page_id = uuid.uuid4().hex
        body = captured.get('text', '')[:24000]
        if not body.strip():
            raise ValueError('This page has no readable text. Try another company page.')
        links = []
        for link in captured.get('links', []):
            try: normalized = website_url(link['url'])
            except ValueError: continue
            if site_host(normalized) == site_host(target):
                links.append({'url':normalized, 'title':str(link.get('title',''))[:200]})
        links = links[:40]
        with self.db() as c:
            c.execute('INSERT INTO company_web_pages VALUES (?,?,?,?,?,?,?)', (page_id, run_id, captured['url'], captured['title'], body, captured['checked'], json.dumps(links)))
        return {'web_page_id': page_id, 'url': captured['url'], 'title': captured['title'], 'text': body,
                'truncated': len(captured.get('text', '')) > len(body), 'links': links, 'checked': captured['checked']}

    def save_fact(self, run_id, field, value, quote, page_id):
        with self.db() as c:
            page = c.execute('SELECT * FROM company_web_pages WHERE id=? AND run_id=?', (page_id, run_id)).fetchone()
            normalize = lambda text: ' '.join(text.split()).casefold()
            if not page or not isinstance(quote, str) or len(quote.strip()) < 12 or normalize(quote) not in normalize(page['body']):
                raise ValueError('Quote the company page exactly, using a web_page_id returned in this workspace’s research.')
            status = 'Company website · model extracted'
            c.execute('INSERT OR REPLACE INTO company_facts VALUES (?,?,?,?,?,?)', (field, value, status, None, None, time.time()))
            c.execute('INSERT OR REPLACE INTO company_web_evidence VALUES (?,?,?)', (field, page_id, quote))
        self.event('profile', 'Company website detail saved', field + ': ' + value[:300])
        return {'field': field, 'value': value, 'status': status, 'source_url': page['url']}
