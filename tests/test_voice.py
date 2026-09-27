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
    async def test_voice_sample_is_wav_cached_per_voice_and_validated(self):
        import base64,wave,shutil
        from app.voice import VoiceSettings
        shutil.rmtree(server.DATA/'voice-samples',ignore_errors=True)
        with self.assertRaises(server.HTTPException) as e:await server.voice_sample(VoiceSettings(voice='Puck'))
        self.assertEqual(e.exception.status_code,503)
        calls=[]
        def fake_urlopen(req,timeout=0):
            calls.append(json.loads(req.data))
            pcm=b'\x00\x10'*2400
            return FakeResponse(json.dumps({'candidates':[{'content':{'parts':[{'inlineData':{'mimeType':'audio/L16;codec=pcm;rate=24000','data':base64.b64encode(pcm).decode()}}]}}]}).encode())
        with patch.dict(os.environ,{'GEMINI_API_KEY':'secret-key'}),patch('app.voice.urllib.request.urlopen',side_effect=fake_urlopen):
            with self.assertRaises(server.HTTPException):await server.voice_sample(VoiceSettings(voice='Robot'))
            first=await server.voice_sample(VoiceSettings(voice='Puck'))
            second=await server.voice_sample(VoiceSettings(voice='Puck'))
        self.assertEqual(first.media_type,'audio/wav')
        with wave.open(io.BytesIO(first.body)) as w:self.assertEqual((w.getframerate(),w.getnchannels(),w.getnframes()),(24000,1,2400))
        self.assertEqual(len(calls),1)   # second request served from the cache
        self.assertEqual(calls[0]['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'],'Puck')
        self.assertTrue((server.DATA/'voice-samples'/'Puck.wav').is_file())
        self.assertEqual(second.body,first.body)

    def setUp(self):
        self.env=patch.dict(os.environ,{'GEMINI_API_KEY':'','BILLY_GEMINI_LIVE_MODEL':'','BILLY_GEMINI_VOICE':''});self.env.start()
        self.addCleanup(self.env.stop)

    async def test_config_and_token_require_a_server_key(self):
        cfg=await server.voice_config()
        self.assertEqual({k:cfg[k] for k in ('provider','model','voice','voice_source','ready')},{'provider':'Gemini Live','model':'gemini-3.8-live','voice':'default','voice_source':'default','ready':False})
        self.assertEqual(len(cfg['voices']),30)
        self.assertNotIn('speechConfig',voice.setup_config()['generationConfig'])
        with patch.dict(os.environ,{'BILLY_GEMINI_VOICE':'Sulafat'}):
            self.assertEqual(voice.setup_config()['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'],'Sulafat')

    async def test_workspace_voice_setting_overrides_the_server_default_per_workspace(self):
        from app.voice import VoiceSettings
        server.save('voice','')
        with patch.dict(os.environ,{'BILLY_GEMINI_VOICE':'Sulafat'}):
            self.assertEqual((await server.voice_config())['voice_source'],'server')
            with self.assertRaises(server.HTTPException):await server.voice_settings(VoiceSettings(voice='Robot'))
            result=await server.voice_settings(VoiceSettings(voice='Achird'))
            self.assertEqual((result['voice'],result['voice_source']),('Achird','workspace'))
            self.assertEqual(voice.setup_config(server.read)['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'],'Achird')
            # The choice lives in this workspace's state table, never in the shared module.
            self.assertEqual(voice.setup_config()['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'],'Sulafat')
            result=await server.voice_settings(VoiceSettings(voice=''))
            self.assertEqual((result['voice'],result['voice_source']),('Sulafat','server'))
        with server.db() as c:
            self.assertEqual(c.execute("SELECT title FROM events ORDER BY id DESC LIMIT 1").fetchone()[0],'Billy’s voice changed')
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
        self.assertEqual(body['bidiGenerateContentSetup']['model'],'models/gemini-3.8-live')
        self.assertEqual(body['bidiGenerateContentSetup']['generationConfig']['responseModalities'],['AUDIO'])
        self.assertEqual([f['name'] for f in body['bidiGenerateContentSetup']['tools'][0]['functionDeclarations']],['ask_billy','billy_reply'])
        self.assertEqual(body['bidiGenerateContentSetup'],result['setup'])
        self.assertLess(body['newSessionExpireTime'],body['expireTime'])
        self.assertEqual(result['token'],'auth_tokens/abc123')
        self.assertEqual(result['setup']['model'],'models/gemini-3.8-live')
        self.assertTrue(result['socket']['url'].startswith('wss://') and 'Constrained' in result['socket']['url'])
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
