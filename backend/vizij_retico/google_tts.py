"""Google Cloud Text-to-Speech — real neural voices with no key.

The keyless default, replacing gTTS. gTTS drives the Google *Translate* endpoint: free
and unofficial, but it returns audio and nothing else — no voices, only accents, and no
timing metadata at all, which is why it can only ever drive amplitude lip-sync.

Cloud TTS is the supported product, and it authenticates with the same ADC as Vertex and
Cloud STT, so a deployment that already has those needs nothing new.

It does *not* replace Polly for lip-sync. Cloud TTS offers SSML `<mark>` timepoints,
which are word-level; Polly emits phoneme-level viseme marks. So: Polly when you want
visemes, this when you want a good voice without credentials.
"""

from __future__ import annotations

from typing import Optional

from .config import CONFIG


def available() -> tuple[bool, str]:
    """(usable, reason) — whether Cloud TTS can be used here."""
    try:
        from google.cloud import texttospeech  # noqa: F401
    except ImportError:
        return False, "google-cloud-texttospeech not installed"
    from . import gcp_auth

    ok, detail = gcp_auth.available()
    return (True, "neural voices") if ok else (False, detail)


_client = None


def client():
    """Lazily build the client so importing this module never needs credentials."""
    global _client
    if _client is None:
        from google.api_core.client_options import ClientOptions
        from google.cloud import texttospeech

        # Pin the quota project for the same reason Cloud STT does: ADC otherwise bills
        # whatever project the local gcloud happens to point at.
        project = CONFIG.google_tts_project or CONFIG.vertex_project
        _client = texttospeech.TextToSpeechClient(
            client_options=ClientOptions(quota_project_id=project) if project else None
        )
    return _client


def language_of(voice: str) -> str:
    """"en-US-Neural2-F" -> "en-US". The API wants both, and they must agree."""
    parts = voice.split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else "en-US"


def synthesize_mp3(text: str, voice: Optional[str] = None) -> bytes:
    from google.cloud import texttospeech

    voice = voice or CONFIG.google_tts_voice
    resp = client().synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(
            language_code=language_of(voice), name=voice
        ),
        # MP3 to match what the browser already plays for the other providers.
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        ),
    )
    return resp.audio_content
