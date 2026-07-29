"""Text-to-speech for the speaking path (lip-sync-first, no keys).

Synthesizes reply text and broadcasts `speech.audio` + `speech.end` events, which the
browser plays and drives the mouth from. Three providers, chosen at runtime:

- google — Cloud TTS neural voices, ADC (no key). The default.
- polly  — the only one returning phoneme-timed visemes, so real lip-sync.
- gtts   — the Google Translate endpoint. No credentials at all, so it is the floor
           every other provider falls back to when it fails mid-utterance.

Only Polly supplies speech marks; the other two leave `visemes` empty and the driver
falls back to amplitude lip-sync.
"""

from __future__ import annotations

import base64
import io
import time
from typing import Callable

from gtts import gTTS

from .events import EventFramer
from .hub import WebSocketHub

# Rough speaking rate, used only to estimate how long an utterance occupies the floor
# when the TTS provider returns no speech marks. Matches the LLM's cooldown heuristic.
CHARS_PER_SECOND = 12.0
# Extra margin after the estimate: playback starts slightly after dispatch, and a room
# has reverb. Too short and the tail of our own sentence is transcribed as the user's.
SPEECH_TAIL_SECONDS = 0.8


# gTTS picks an accent from a lang/tld pair, not a voice name. The voice registry uses
# "en-uk"-style ids so one selector can serve both providers; unpack them here.
_GTTS_ACCENTS = {"en": ("en", "com"), "en-uk": ("en", "co.uk"),
                 "en-au": ("en", "com.au"), "en-in": ("en", "co.in")}


def _gtts_lang(voice: str) -> str:
    """A Polly voice name selected before switching to gTTS is meaningless here."""
    return voice if voice in _GTTS_ACCENTS else "en"


def synthesize_mp3(text: str, lang: str = "en") -> bytes:
    code, tld = _GTTS_ACCENTS.get(lang, ("en", "com"))
    buf = io.BytesIO()
    gTTS(text=text, lang=code, tld=tld).write_to_fp(buf)
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
                    speech = polly.synthesize(text, getattr(hub, "voice", None) or CONFIG.polly_voice)
                    mp3 = speech.audio
                    visemes = speech.marks.get("visemes", [])
                except Exception as exc:
                    # Never lose the utterance to a TTS outage — say it with gTTS and
                    # fall back to amplitude lip-sync.
                    print(f"[tts] polly failed ({exc}); falling back to gTTS")
                    mp3 = synthesize_mp3(text)
            elif provider == "google":
                from . import google_tts

                try:
                    mp3 = google_tts.synthesize_mp3(text, getattr(hub, "voice", "") or None)
                except Exception as exc:
                    print(f"[tts] cloud tts failed ({exc}); falling back to gTTS")
                    mp3 = synthesize_mp3(text)
            else:
                mp3 = synthesize_mp3(text, _gtts_lang(getattr(hub, "voice", "") or "en"))
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
        # Record what we are saying so the ASR gate can recognise it coming back through
        # the microphone (see echo.py). The duration only decides how long we consider
        # ourselves "still speaking" — the actual echo test is on the text, so an
        # inaccurate estimate no longer swallows the user's turn. Visemes give the real
        # length when Polly produced them; otherwise use a speaking-rate estimate.
        if visemes:
            spoken = visemes[-1].get("time", 0) / 1000.0
        else:
            spoken = len(text) / CHARS_PER_SECOND
        hub.note_speaking(text, spoken + SPEECH_TAIL_SECONDS)

    return say
