import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-voice-test-'))
from app import server
from app import voice

class FakeResponse(io.BytesIO):
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

class VoiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'GEMINI_API_KEY':'','BILLY_GEMINI_LIVE_MODEL':''});self.env.start()
        self.addCleanup(self.env.stop)

    async def test_config_and_token_require_a_server_key(self):
        self.assertEqual(await server.voice_config(),{'provider':'Gemini Live','model':'gemini-3.8-live','ready':False})
        with self.assertRaises(server.HTTPException) as e:await server.voice_token()
        self.assertEqual(e.exception.status_code,503)

    async def test_token_is_minted_server_side_with_locked_model(self):
        captured={}
        def fake_urlopen(req,timeout=0):
            captured['url']=req.full_url;captured['headers']=dict(req.header_items());captured['body']=json.loads(req.data)
            return FakeResponse(json.dumps({'name':'auth_tokens/abc123'}).encode())
        with patch.dict(os.environ,{'GEMINI_API_KEY':'secret-key','BILLY_GEMINI_LIVE_MODEL':'gemini-3.8-live'}),patch('app.voice.urllib.request.urlopen',side_effect=fake_urlopen):
            self.assertTrue((await server.voice_config())['ready'])
            result=await server.voice_token()
        self.assertEqual(captured['url'],voice.TOKEN_URL)
        self.assertEqual(captured['headers'].get('X-goog-api-key'),'secret-key')
        body=captured['body']
        self.assertEqual(body['uses'],1)
        self.assertEqual(body['liveConnectConstraints']['model'],'models/gemini-3.8-live')
        self.assertEqual(body['liveConnectConstraints']['config']['responseModalities'],['AUDIO'])
        self.assertLess(body['newSessionExpireTime'],body['expireTime'])
        self.assertEqual(result['token'],'auth_tokens/abc123')
        self.assertEqual(result['setup']['model'],'models/gemini-3.8-live')
        self.assertEqual([f['name'] for f in result['setup']['tools'][0]['functionDeclarations']],['ask_billy','billy_reply'])
        self.assertIn('never invent',result['setup']['systemInstruction']['parts'][0]['text'].lower())
        self.assertNotIn('secret-key',json.dumps(result))
        with server.db() as c:
            self.assertEqual(c.execute("SELECT title FROM events ORDER BY id DESC LIMIT 1").fetchone()[0],'Voice session opened')

    async def test_upstream_failure_never_leaks_the_response(self):
        import urllib.error
        def failing(req,timeout=0):raise urllib.error.HTTPError(req.full_url,400,'Bad Request',{},io.BytesIO(b'{"error":"key secret-key rejected"}'))
        with patch.dict(os.environ,{'GEMINI_API_KEY':'secret-key'}),patch('app.voice.urllib.request.urlopen',side_effect=failing):
            with self.assertRaises(server.HTTPException) as e:await server.voice_token()
        self.assertEqual(e.exception.status_code,502)
        self.assertNotIn('secret-key',e.exception.detail)
        def empty(req,timeout=0):return FakeResponse(b'{}')
        with patch.dict(os.environ,{'GEMINI_API_KEY':'secret-key'}),patch('app.voice.urllib.request.urlopen',side_effect=empty):
            with self.assertRaises(server.HTTPException) as e:await server.voice_token()
        self.assertEqual(e.exception.status_code,502)

if __name__=='__main__':unittest.main()
