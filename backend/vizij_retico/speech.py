"""Text-to-speech for the speaking path (lip-sync-first, no keys).

Synthesizes reply text with gTTS (MP3, no API key; needs internet) and broadcasts
`speech.audio` + `speech.end` events. The browser plays the audio and drives the
mouth from its amplitude (this rig has a jaw channel, not phoneme viseme poses).
"""

from __future__ import annotations

import base64
import io
from typing import Callable

from gtts import gTTS

from .events import EventFramer
from .hub import WebSocketHub


def synthesize_mp3(text: str, lang: str = "en") -> bytes:
    buf = io.BytesIO()
    gTTS(text=text, lang=lang).write_to_fp(buf)
    return buf.getvalue()


def make_say_handler(hub: WebSocketHub, framer: EventFramer) -> Callable[[str], None]:
    """Return a handler that synthesizes `text` and broadcasts speech events.

    Runs on a worker thread (the hub spawns it), so the blocking gTTS network call
    never touches the asyncio loop.
    """
    counter = {"n": 0}

    def say(text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        counter["n"] += 1
        utterance_id = f"u_{counter['n']}"
        visemes: list[dict] = []
        provider = getattr(hub, "tts_provider", "gtts")
        try:
            if provider == "polly":
                from . import polly
                from .config import CONFIG

                try:
                    speech = polly.synthesize(text, CONFIG.polly_voice)
                    mp3 = speech.audio
                    visemes = speech.marks.get("visemes", [])
                except Exception as exc:
                    # Never lose the utterance to a TTS outage — say it with gTTS and
                    # fall back to amplitude lip-sync.
                    print(f"[tts] polly failed ({exc}); falling back to gTTS")
                    mp3 = synthesize_mp3(text)
            else:
                mp3 = synthesize_mp3(text)
        except Exception as exc:  # network / gTTS failure
            hub.broadcast(
                framer.frame("speech.error", {"utteranceId": utterance_id, "error": str(exc)})
            )
            return
        hub.broadcast(
            framer.frame(
                "speech.audio",
                {
                    "utteranceId": utterance_id,
                    "text": text,
                    "format": "audio/mpeg;base64",
                    "data": base64.b64encode(mp3).decode("ascii"),
                    # Present only for providers that return speech marks; the driver
                    # falls back to amplitude lip-sync when this is empty.
                    "visemes": visemes,
                },
            )
        )
        hub.broadcast(framer.frame("speech.end", {"utteranceId": utterance_id}))

    return say
