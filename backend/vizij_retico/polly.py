"""AWS Polly TTS with phoneme-timed speech marks (visemes).

gTTS gives audio only, so lip-sync has to be inferred from amplitude — the mouth opens
and closes but never forms shapes. Polly returns *speech marks* alongside the audio: a
timestamped stream of visemes, which is what the rig's viseme poses actually want.

Two surfaces:
- `synthesize()` is used by the say-handler, so retico keeps deciding *when* to speak and
  the visemes ride along in the `speech.audio` event.
- `/tts/get-audio` and `/tts/get-visemes` implement the contract `@vizij/speech-react`
  expects (`fetchVisemeData`), so that library — and other vizij apps — can drive this
  backend directly.

Credentials come from the usual AWS environment/profile chain; nothing is accepted from
the client.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

# Speech mark types Polly can emit; the face only needs visemes, but words/sentences are
# cheap and useful for captions and for aligning gestures to clause boundaries.
MARK_TYPES = ["sentence", "word", "viseme"]


@dataclass
class Speech:
    audio: bytes
    """MP3 bytes."""
    marks: dict[str, list[dict[str, Any]]]
    """{"sentences": [...], "words": [...], "visemes": [...]} — each {time, type, value}."""


_client = None


def client():
    """Lazily build the Polly client so importing this module never needs boto3/creds."""
    global _client
    if _client is None:
        import boto3

        _client = boto3.client("polly")
    return _client


def _parse_marks(raw: bytes) -> dict[str, list[dict[str, Any]]]:
    """Polly returns newline-delimited JSON, not a JSON array."""
    out: dict[str, list[dict[str, Any]]] = {"sentences": [], "words": [], "visemes": []}
    bucket = {"sentence": "sentences", "word": "words", "viseme": "visemes"}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            mark = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = bucket.get(mark.get("type", ""))
        if key:
            out[key].append(mark)
    return out


def _synthesize(text: str, voice: str, output_format: str, engine: str = "neural", **kw):
    try:
        return client().synthesize_speech(
            Text=text, VoiceId=voice, OutputFormat=output_format, Engine=engine, **kw
        )
    except Exception:
        # Not every voice supports the neural engine; standard is the safe fallback.
        if engine != "standard":
            return client().synthesize_speech(
                Text=text, VoiceId=voice, OutputFormat=output_format, Engine="standard", **kw
            )
        raise


def synthesize_audio(text: str, voice: str) -> bytes:
    return _synthesize(text, voice, "mp3")["AudioStream"].read()


def synthesize_marks(text: str, voice: str) -> dict[str, list[dict[str, Any]]]:
    resp = _synthesize(text, voice, "json", SpeechMarkTypes=MARK_TYPES)
    return _parse_marks(resp["AudioStream"].read())


def synthesize(text: str, voice: str) -> Speech:
    """Audio + speech marks for one utterance (two Polly calls; they're independent)."""
    return Speech(audio=synthesize_audio(text, voice), marks=synthesize_marks(text, voice))


def register_routes(app, default_voice: str) -> None:
    """Expose the `@vizij/speech-react` TTS contract on the shared FastAPI app."""
    from fastapi import HTTPException
    from fastapi.responses import Response

    def _text_voice(payload: Optional[dict]) -> tuple[str, str]:
        payload = payload or {}
        text = (payload.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        return text, payload.get("voice") or default_voice

    @app.post("/tts/get-visemes")
    async def get_visemes(payload: dict) -> dict[str, Any]:
        text, voice = _text_voice(payload)
        try:
            return synthesize_marks(text, voice)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Polly: {exc}") from exc

    @app.post("/tts/get-audio")
    async def get_audio(payload: dict) -> Response:
        text, voice = _text_voice(payload)
        try:
            return Response(content=synthesize_audio(text, voice), media_type="audio/mpeg")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Polly: {exc}") from exc
