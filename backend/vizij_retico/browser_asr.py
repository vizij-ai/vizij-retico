"""BrowserASRModule — browser Web Speech API transcripts → retico IUs.

An alternative to retico-whisperasr: the browser (Chrome's Web Speech API) does the
transcription and streams the recognized text to the backend over the WebSocket. This
module drains those transcripts from the hub and re-emits them as `SpeechRecognitionIU`s
that are byte-for-byte compatible with the Whisper path — one ADD per word, then a
COMMIT at end-of-utterance — so the downstream classifier and LLM don't care which ASR
produced them.

Only *final* browser results reach the hub (see hub `input.asr`); interim results are
shown live in the browser and never enter the retico graph, so the accumulated tokens
always equal the final transcript.
"""

from __future__ import annotations

import queue

import retico_core
from retico_core.text import SpeechRecognitionIU

from .hub import WebSocketHub


class BrowserASRModule(retico_core.AbstractProducingModule):
    @staticmethod
    def name() -> str:
        return "Browser ASR Module"

    @staticmethod
    def description() -> str:
        return "Emits SpeechRecognitionIUs from browser Web Speech API transcripts (via the hub)."

    @staticmethod
    def output_iu():
        return SpeechRecognitionIU

    def __init__(self, hub: WebSocketHub, **kwargs) -> None:
        super().__init__(**kwargs)
        self.hub = hub

    def process_update(self, _):
        try:
            item = self.hub.asr_in.get(timeout=1.0)
        except queue.Empty:
            return None
        text = (item.get("text") or "").strip()
        if not text:
            return None

        # Mirror Whisper's incremental contract: one ADD per token, then a COMMIT.
        update = retico_core.UpdateMessage()
        words = text.split()
        prev = None
        for i, word in enumerate(words):
            iu = self.create_iu(prev)
            final = i == len(words) - 1
            iu.set_asr_results([word], word, 0.0, 1.0, final)
            update.add_iu(iu, retico_core.UpdateType.ADD)
            prev = iu
        commit = self.create_iu(prev)
        commit.set_asr_results([text], text, 0.0, 1.0, True)
        update.add_iu(commit, retico_core.UpdateType.COMMIT)
        return update
