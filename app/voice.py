"""Live voice: mint short-lived Gemini Live tokens so the browser can talk to Billy.

Gemini is Billy's ears and mouth only. It gets two functions, ask_billy and
billy_reply, which the browser executes against this workspace's agent API.
GLM on Vultr remains the only agent; the Gemini API key never leaves the server.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

TOKEN_URL = 'https://generativelanguage.googleapis.com/v1beta/auth_tokens'
DEFAULT_MODEL = 'gemini-3.8-live'
TOKEN_LIFETIME = timedelta(minutes=30)
NEW_SESSION_WINDOW = timedelta(minutes=2)

VOICE_INSTRUCTION = '''You are the voice of Billy, an RFP agent. You are not Billy: Billy is a separate agent that reads documents, saves company facts and prepares proposals. You only listen and speak for him.
Rules: for anything about the company, its documents, RFPs, opportunities, drafts, deadlines or Billy's work, call ask_billy with the user's request in their own words and speak Billy's reply naturally, without adding facts of your own. Never answer those questions yourself, never invent company details, prices, insurance, qualifications or deadlines, and never claim work was done unless Billy's reply says so.
If ask_billy reports that Billy is still working, say briefly that he is on it, and use billy_reply when the user asks what he found. Keep every turn short, warm and practical, like a colleague on the phone. Greetings, small talk and clarifying what the user wants can be handled directly. Billy cannot submit, email, sign or buy anything; if asked, say the user submits through the agency after review.'''

FUNCTIONS = [
    {'name': 'ask_billy',
     'description': "Send the user's spoken request to Billy, the RFP agent, and get his reply. Use for any question or instruction about the company, documents, RFPs, opportunities, drafts, deadlines or Billy's work.",
     'parameters': {'type': 'OBJECT', 'properties': {'message': {'type': 'STRING', 'description': "The user's request in their own words."}}, 'required': ['message']}},
    {'name': 'billy_reply',
     'description': 'Read Billy\'s latest reply and whether he is still working, after an earlier ask_billy said he was busy.',
     'parameters': {'type': 'OBJECT', 'properties': {}}},
]


def gemini_key():
    return os.environ.get('GEMINI_API_KEY', '')


def live_model():
    return os.environ.get('BILLY_GEMINI_LIVE_MODEL') or DEFAULT_MODEL


def voice_config():
    return {'provider': 'Gemini Live', 'model': live_model(), 'ready': bool(gemini_key())}


def setup_config():
    """The Live session setup the browser sends. Kept server-side as the single source of truth."""
    return {'model': 'models/' + live_model(),
            'generationConfig': {'responseModalities': ['AUDIO']},
            'systemInstruction': {'parts': [{'text': VOICE_INSTRUCTION}]},
            'tools': [{'functionDeclarations': FUNCTIONS}],
            'inputAudioTranscription': {}, 'outputAudioTranscription': {},
            'sessionResumption': {}}


def request_token(body):
    req = urllib.request.Request(TOKEN_URL, data=json.dumps(body).encode(),
                                 headers={'x-goog-api-key': gemini_key(), 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read(64 * 1024))


def register_voice(app, event):
    @app.get('/api/voice/config')
    async def config():
        return voice_config()

    @app.post('/api/voice/token')
    async def token():
        if not gemini_key():
            raise HTTPException(503, 'Live voice is not connected. Add a Gemini API key on the server.')
        now = datetime.now(timezone.utc)
        expires = now + TOKEN_LIFETIME
        new_session = now + NEW_SESSION_WINDOW
        stamp = lambda t: t.strftime('%Y-%m-%dT%H:%M:%SZ')
        body = {'uses': 1, 'expireTime': stamp(expires), 'newSessionExpireTime': stamp(new_session),
                'liveConnectConstraints': {'model': 'models/' + live_model(),
                                           'config': {'responseModalities': ['AUDIO'], 'sessionResumption': {}}}}
        try:
            import asyncio
            result = await asyncio.to_thread(request_token, body)
        except Exception:
            # Never forward the upstream body or headers; they can echo the key or account details.
            raise HTTPException(502, 'Gemini could not issue a voice session token. Check the key and model on the server, then try again.') from None
        name = result.get('name') if isinstance(result, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(502, 'Gemini returned no voice session token.')
        event('voice', 'Voice session opened', f'Gemini Live · {live_model()} · token valid until {stamp(expires)}')
        return {'token': name, 'model': live_model(), 'expires_at': stamp(expires), 'new_session_expires_at': stamp(new_session),
                'setup': setup_config(),
                'audio': {'input': {'mime_type': 'audio/pcm;rate=16000', 'rate': 16000}, 'output': {'rate': 24000}},
                'note': 'The token opens one Live session. Function calls run in the browser against this workspace only.'}

    return config, token
