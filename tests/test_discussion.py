import asyncio
import io
import os
import tempfile
import unittest
import wave
from unittest.mock import patch
os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-discuss-test-'))
from app import server
from app.discussion import DiscussionTurn, validate_audio
from fastapi import UploadFile

class DiscussionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with server.db() as c:
            for table in ('company_facts','company_tasks','company_messages','discussion_messages'):
                c.execute('DELETE FROM '+table)
        self.env=patch.dict(os.environ,{'META_API_KEY':'','MODEL_API_KEY':''});self.env.start()
        self.addCleanup(self.env.stop)

    async def open(self,**kw):
        return await server.discuss(DiscussionTurn(**kw))

    async def test_agenda_topic_opens_exact_question_without_saving_a_fact(self):
        self.assertEqual((await self.open(field='company.overview'))['messages'],[])
        before=await server.company_profile()
        question='Do you have a current insurance certificate we can add?'
        result=await self.open(field='insurance.coverage',opening_question=question)
        self.assertEqual([(m['role'],m['text']) for m in result['messages']],[('billy',question)])
        self.assertEqual(await server.company_profile(),before)
        with self.assertRaises(server.HTTPException):await self.open(field='made.up')

    async def test_repeated_agenda_clicks_never_duplicate_the_opening_question(self):
        question='Do you have a current insurance certificate we can add?'
        async def open_topic():
            return await self.open(field='insurance.coverage',opening_question=' '+question+' ')
        await asyncio.gather(open_topic(),open_topic(),open_topic())
        result=await open_topic()
        self.assertEqual([m['text'] for m in result['messages']],[question])

    async def test_distinct_questions_in_same_rfp_scope_still_open(self):
        rfp=(await server.create_rfp(server.RFPInput(title='Agenda questions')))['id']
        for question in ['Who is the project lead?','When can the team start?','Who is the project lead?']:
            result=await self.open(rfp_id=rfp,opening_question=question)
        self.assertEqual([m['text'] for m in result['messages']],['Who is the project lead?','When can the team start?'])
        with self.assertRaises(server.HTTPException):await self.open(rfp_id='missing',opening_question='x')
        with self.assertRaises(server.HTTPException):await self.open(rfp_id=rfp,section='9',opening_question='x')

    async def test_voice_requires_key_and_validates_wav(self):
        self.assertFalse((await server.discussion_config())['voice_ready'])
        with self.assertRaises(server.HTTPException) as e:await server.transcribe(UploadFile(file=io.BytesIO(b'bad')))
        self.assertEqual(e.exception.status_code,503)
        with self.assertRaises(server.HTTPException):validate_audio(b'not WAV')
        def wav(rate=24000,channels=1):
            out=io.BytesIO()
            with wave.open(out,'wb') as w:
                w.setnchannels(channels);w.setsampwidth(2);w.setframerate(rate);w.writeframes(b'\0\0'*rate*channels)
            return out.getvalue()
        validate_audio(wav())
        with self.assertRaises(server.HTTPException):validate_audio(wav(channels=2))
        before=await server.company_profile()
        with patch.dict(os.environ,{'META_API_KEY':'unit-test-key'}),patch('app.discussion.post_meta',return_value={'transcript':'We have $1M from our carrier'}) as provider:
            result=await server.transcribe(UploadFile(file=io.BytesIO(wav())))
        self.assertEqual(result['text'],'We have $1M from our carrier')
        self.assertEqual(await server.company_profile(),before) # Transcription alone never applies changes.
        self.assertEqual(provider.call_args.args[0],'asr/transcribe')
        self.assertIn(b'muse-voice-transcribe-1.0',provider.call_args.args[1])

if __name__=='__main__':unittest.main()
