"""Agenda openers for main chat and a server-only Meta push-to-talk transcription bridge."""
import asyncio
import io
import json
import os
import time
import uuid
import wave
import urllib.request
import urllib.error
from fastapi import HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from app.company import FIELDS

class DiscussionTurn(BaseModel):
    field: str = ''
    rfp_id: str = ''
    section: str = 'files'
    opening_question: str = Field(default='',max_length=2000)


def meta_key():
    return os.environ.get('META_API_KEY') or os.environ.get('MODEL_API_KEY')


def post_meta(path,body,content_type):
    req=urllib.request.Request('https://api.meta.ai/v1/'+path,data=body,headers={
        'Authorization':'Bearer '+meta_key(),'Content-Type':content_type})
    try:
        with urllib.request.urlopen(req,timeout=45) as response:
            return json.loads(response.read(2*1024*1024))
    except Exception:
        # Never forward upstream response bodies, request headers, or credentials.
        raise HTTPException(502,'Meta could not complete this request. Your saved work is unchanged; try again or use text.')


def validate_audio(raw):
    try:
        with wave.open(io.BytesIO(raw),'rb') as wav:
            if wav.getnchannels()!=1 or wav.getsampwidth()!=2 or wav.getframerate() not in (16000,24000) or wav.getcomptype()!='NONE': raise ValueError()
            duration=wav.getnframes()/wav.getframerate()
            if not 0.2<=duration<=65: raise ValueError()
            if len(wav.readframes(wav.getnframes()))!=wav.getnframes()*2: raise ValueError()
    except (wave.Error,EOFError,ValueError):
        raise HTTPException(400,'Record 1–60 seconds of mono PCM WAV audio at 16 or 24 kHz.')


def register_discussion(app,db,require_rfp):
    lock=asyncio.Lock()
    voice_lock=asyncio.Lock()
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS discussion_messages(id INTEGER PRIMARY KEY,scope TEXT,role TEXT,text TEXT,at REAL)')

    def scope(req):
        if req.field and req.field not in FIELDS: raise HTTPException(400,'Unknown company detail.')
        if req.rfp_id:
            require_rfp(req.rfp_id)
            if req.section not in ('files','1','2','3'): raise HTTPException(400,'Unknown RFP section.')
            return f'rfp:{req.rfp_id}:{req.section}'
        return 'company:'+req.field if req.field else 'general'

    def messages(key):
        with db() as c: return [dict(r) for r in c.execute('SELECT role,text,at FROM discussion_messages WHERE scope=? ORDER BY id',(key,))]

    @app.get('/api/discussion/agenda')
    async def agenda():
        from app.discussion_agenda import build_agenda
        return build_agenda(db)

    @app.get('/api/discussion/config')
    async def discussion_config():
        return {'voice_ready':bool(meta_key()),'voice_provider':'Meta Muse Voice Transcribe'}

    @app.post('/api/discussion')
    async def discuss(req:DiscussionTurn):
        """Open a topic. The opening question is recorded once per scope so the main agent
        sees it as Billy's prior turn; the user's answer itself goes to /agent/message."""
        key=scope(req)
        question=req.opening_question.strip()
        async with lock:
            history=messages(key)
            if question and not any(m['role']=='billy' and m['text']==question for m in history):
                with db() as c:
                    c.execute('INSERT INTO discussion_messages(scope,role,text,at) VALUES (?,?,?,?)',(key,'billy',question,time.time()))
                history=messages(key)
        return {'messages':history}

    @app.post('/api/discussion/transcribe')
    async def transcribe(file:UploadFile=File(...)):
        if not meta_key(): raise HTTPException(503,'Connect a Meta Model API key on the server to enable voice. Text discussion is available now.')
        raw=await file.read(4*1024*1024+1)
        await file.close()
        if len(raw)>4*1024*1024: raise HTTPException(413,'Record up to 60 seconds at a time.')
        validate_audio(raw)
        request={'model':'muse-voice-transcribe-1.0','audioEncoding':'WAV','mode':'PUSH_TO_TALK','languageBias':['English'],'keywords':['RFP','liability','insurance','proposal']}
        boundary=uuid.uuid4().hex
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="request"\r\nContent-Type: application/json\r\n\r\n'.encode()+json.dumps(request).encode()+f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+raw+f'\r\n--{boundary}--\r\n'.encode())
        async with voice_lock:
            result=await asyncio.to_thread(post_meta,'asr/transcribe',body,'multipart/form-data; boundary='+boundary)
        transcript=result.get('transcript','')
        if not isinstance(transcript,str) or not transcript.strip(): raise HTTPException(422,'No speech was detected. Try again or type your answer.')
        if len(transcript)>6000: raise HTTPException(422,'That transcript is too long. Try a shorter recording.')
        # Audio is not written to disk; only an explicitly sent transcript is persisted.
        return {'text':transcript.strip()}

    return discuss,discussion_config,transcribe
