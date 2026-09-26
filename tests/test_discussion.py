import io
import os
import tempfile
import unittest
import wave
from unittest.mock import patch
os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-discuss-test-'))
from app import server
from app.company import ProfileAnswer, insurance_details
from app.discussion import DiscussionTurn, validate_audio
from fastapi import UploadFile

class DiscussionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with server.db() as c:
            for table in ('company_facts','company_tasks','company_messages','company_dialogue','discussion_messages','discussion_context','discussion_outcomes'):
                c.execute('DELETE FROM '+table)
        self.env=patch.dict(os.environ,{'META_API_KEY':'','MODEL_API_KEY':''});self.env.start()
        self.addCleanup(self.env.stop)

    async def turn(self,text='',**kw):
        return await server.discuss(DiscussionTurn(text=text,**kw))

    async def test_example_extracts_then_waits_for_explicit_acceptance(self):
        await self.turn(action='insurance_example',field='insurance.coverage')
        result=await self.turn('We have 1M through the Hartford in liability coverage.',field='insurance.coverage')
        self.assertIn('illustrative',result['messages'][-1]['text'])
        facts=(await server.company_profile())['facts']
        self.assertIn('1,000,000',facts['insurance.limits']['value'])
        self.assertIn('Hartford',facts['insurance.insurer']['value'])
        self.assertEqual(len(result['changes']),3)
        self.assertEqual(result['tasks'],[])
        await self.turn('Maybe later',field='insurance.coverage')
        self.assertEqual((await server.company_profile())['tasks'],[])
        result=await self.turn('Yes',field='insurance.coverage')
        self.assertEqual(result['tasks'][0]['kind'],'research')
        self.assertEqual((await server.company_profile())['facts'],facts)
        history=await self.turn(action='start',field='insurance.coverage')
        self.assertEqual(history['messages'],result['messages'])
        self.assertEqual(len(history['changes']),3)
        self.assertEqual(len(history['tasks']),1)

    async def test_questions_do_not_write_or_destroy_evidence(self):
        await server.company_chat(ProfileAnswer(field='insurance.coverage',text='Existing policy',action='edit'))
        with server.db() as c:c.execute("UPDATE company_facts SET document_id='existing-evidence',status='Evidence linked' WHERE field='insurance.coverage'")
        before=(await server.company_profile())['facts']
        await self.turn('Does this RFP require liability insurance?')
        await self.turn('We could have $1M from Hartford if approved')
        self.assertEqual((await server.company_profile())['facts'],before)
        self.assertEqual((await server.company_profile())['tasks'],[])

    async def test_explicit_requirement_field_and_saved_requirement_gap(self):
        await self.turn('RFP requires $5M liability insurance',field='insurance.requirement')
        facts=(await server.company_profile())['facts']
        self.assertNotIn('insurance.coverage',facts)
        self.assertIn('5M',facts['insurance.requirement']['value'])
        result=await self.turn('We have $1M general liability through Hartford',field='insurance.coverage')
        self.assertIn('requirement saved in your company profile',result['messages'][-1]['text'])
        self.assertNotIn('illustrative',result['messages'][-1]['text'])
        self.assertEqual(result['tasks'],[])

    async def test_rfp_scopes_keep_offers_and_notes_separate(self):
        a=(await server.create_rfp(server.RFPInput(title='A')))['id']
        b=(await server.create_rfp(server.RFPInput(title='B')))['id']
        await self.turn('No insurance',rfp_id=a)
        await self.turn('Yes, we have liability coverage',rfp_id=b)
        self.assertFalse(any(t['kind']=='research' for t in (await server.company_profile())['tasks']))
        self.assertEqual(len((await server.rfp_workspace(a))['notes']),1)
        self.assertEqual(len((await server.rfp_workspace(b))['notes']),1)
        self.assertEqual((await server.rfp_workspace(a))['progress'],0)
        result=await self.turn('Yes',rfp_id=a)
        self.assertEqual(result['tasks'][0]['kind'],'research')

    async def test_ambiguous_money_and_unknowns_do_not_set_limit(self):
        for text in ['We have a $1M deductible on our Hartford policy','We have $1M per occurrence and $2M aggregate through Hartford','We have a $500 premium with Hartford','Do we have $5M with Hartford?']:
            self.assertNotIn('insurance.limits',insurance_details(text))
        await self.turn('We have $1M liability through Hartford',field='insurance.coverage')
        reply=(await self.turn(action='start',field='insurance.coverage'))['messages'][-1]['text']
        self.assertNotIn('$5',reply)

    async def test_inferred_topic_does_not_overwrite_coverage_with_team_or_requirements(self):
        await self.turn('We have $1M liability coverage with Hartford')
        before=(await server.company_profile())['facts']
        await self.turn('Our project team has four people')
        self.assertEqual((await server.company_profile())['facts'],before)
        await self.turn('The RFP insurance requirement is $5M')
        self.assertEqual((await server.company_profile())['facts'],before)
        await self.turn('Our lead is available tomorrow')
        self.assertEqual((await server.company_profile())['facts'],before)

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
        with patch.dict(os.environ,{'META_API_KEY':'unit-test-key'}),patch('app.discussion.post_meta',return_value={'transcript':'We have $1M from Hartford'}) as provider:
            result=await server.transcribe(UploadFile(file=io.BytesIO(wav())))
        self.assertEqual(result['text'],'We have $1M from Hartford')
        self.assertEqual(await server.company_profile(),before) # Transcription alone never applies changes.
        self.assertEqual(provider.call_args.args[0],'asr/transcribe')
        self.assertIn(b'muse-voice-transcribe-1.0',provider.call_args.args[1])

if __name__=='__main__':unittest.main()
