import asyncio
import json
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-web-test-'))
from app import server
from app.company import ProfileAnswer
from app.company_web import CompanyWebsite

class CompanyWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with server.db() as c:
            for table in ('company_web_evidence','company_web_pages','company_facts','agent_messages'):
                c.execute('DELETE FROM '+table)
            c.execute('INSERT INTO company_facts VALUES (?,?,?,?,?,?)',('company.website','https://example.com','Reported by you',None,None,time.time()))
            c.execute('INSERT INTO agent_messages(run_id,role,text,created) VALUES (?,?,?,?)',('web-test','user','Learn about my company from its website.',time.time()))
        self.captured={'url':'https://www.example.com/','title':'Example company','text':'We provide electrical installation and maintenance.','checked':time.time(),'links':[{'url':'https://example.com/services','title':'Services'},{'url':'https://other.example/','title':'External'}]}
        async def research(url,company=False):
            self.browser.busy=False
            return dict(self.captured)
        self.browser=SimpleNamespace(busy=False,controller='billy',pending=None,error=None,task=None,research=AsyncMock(side_effect=research))
        self.validate=AsyncMock()
        self.web=CompanyWebsite(server.db,self.browser,self.validate,lambda *args:None)

    async def test_saved_site_and_cited_profile_fact(self):
        page=await self.web.read('web-test')
        self.browser.research.assert_awaited_once_with('https://example.com/',company=True)
        self.assertEqual(len(page['links']),1)
        self.web.save_fact('web-test','experience.services','Electrical installation and maintenance.',self.captured['text'],page['web_page_id'])
        profile=await server.company_profile()
        self.assertEqual(profile['facts']['experience.services']['source_url'],self.captured['url'])
        self.assertEqual(profile['facts']['experience.services']['source_quote'],self.captured['text'])
        await self.web.read('web-test','https://example.com/services')
        await server.company_chat(ProfileAnswer(field='experience.services',text='Updated by owner',action='edit'))
        self.assertNotIn('source_url',(await server.company_profile())['facts']['experience.services'])

    async def test_unapproved_urls_and_fabricated_quotes_rejected(self):
        for url in ['http://127.0.0.1/','https://unrelated.example/','https://example.com/not-seen']:
            with self.assertRaises(ValueError):await self.web.read('web-test',url)
        self.browser.research.assert_not_awaited()
        page=await self.web.read('web-test')
        with self.assertRaises(ValueError):self.web.save_fact('web-test','insurance.coverage','$5M','We carry $5M of liability insurance.',page['web_page_id'])
        with self.assertRaises(ValueError):self.web.save_fact('other-run','experience.services','Electrical',self.captured['text'],page['web_page_id'])

    async def test_user_url_is_allowed_but_public_url_check_and_handoff_still_apply(self):
        with server.db() as c:
            c.execute('INSERT INTO agent_messages(run_id,role,text,created) VALUES (?,?,?,?)',('web-test','user','Please read https://new.example/',time.time()))
        self.captured['url']='https://new.example/'
        await self.web.read('web-test','https://new.example/')
        self.validate.assert_awaited_with('https://new.example/')
        self.browser.controller='you'
        with self.assertRaises(server.HTTPException):await self.web.read('web-test','https://new.example/')
        self.browser.controller='billy'
        self.validate.side_effect=server.HTTPException(400,'Private address')
        with self.assertRaises(server.HTTPException):await self.web.read('web-test','https://new.example/')

    async def test_bare_domain_user_input_is_accepted_without_guessing_from_email(self):
        with server.db() as c:
            c.execute("DELETE FROM company_facts WHERE field='company.website'")
            c.execute('INSERT INTO agent_messages(run_id,role,text,created) VALUES (?,?,?,?)',('web-test','user','Learn about us at new.example.',time.time()))
        self.captured['url']='https://new.example/'
        await self.web.read('web-test','https://new.example/')
        with server.db() as c:
            c.execute('INSERT INTO agent_messages(run_id,role,text,created) VALUES (?,?,?,?)',('web-test','user','Contact me at owner@different.example.',time.time()))
        with self.assertRaisesRegex(ValueError,'Ask for the company website'):
            await self.web.read('web-test','https://different.example/')

    async def test_redirects_and_failed_reads_never_produce_citable_pages(self):
        self.captured['url']='https://unrelated.example/'
        with self.assertRaises(ValueError):await self.web.read('web-test')
        with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM company_web_pages').fetchone()[0],0)
        self.browser.error='Failed to load'
        with self.assertRaises(ValueError):await self.web.read('web-test')

    async def test_page_limit_is_per_user_turn(self):
        for _ in range(4):
            self.captured['checked']=time.time()
            await self.web.read('web-test')
        with self.assertRaisesRegex(ValueError,'Four company pages'):await self.web.read('web-test')
        with server.db() as c:c.execute('INSERT INTO agent_messages(run_id,role,text,created) VALUES (?,?,?,?)',('web-test','user','Continue reading my company website.',time.time()))
        await self.web.read('web-test')
