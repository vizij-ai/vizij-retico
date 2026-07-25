"""TTSModule — speakable text in, synthesized speech out.

Split out from the LLM so the two stages are independent: the LLM streams clauses as it
generates, and this module speaks them in order. That's what lets the agent start talking
before the reply is finished.

Synthesis happens on a single worker thread draining a queue, which matters for two
reasons: it keeps the (blocking, network-bound) TTS call off retico's module thread, and
it guarantees clauses are broadcast in the order they were generated — the browser plays
`speech.audio` events as they arrive, so out-of-order synthesis would scramble the reply.
"""

from __future__ import annotations

import queue
import threading
from typing import Callable

import retico_core
from retico_core.text import GeneratedTextIU


class TTSModule(retico_core.AbstractConsumingModule):
    @staticmethod
    def name() -> str:
        return "TTS Module"

    @staticmethod
    def description() -> str:
        return "Synthesizes incoming text clauses to speech, in order."

    @staticmethod
    def input_ius():
        return [GeneratedTextIU]

    def __init__(self, say: Callable[[str], None], **kwargs) -> None:
        super().__init__(**kwargs)
        self.say = say
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._worker = threading.Thread(target=self._drain, daemon=True)
        self._worker.start()

    def process_update(self, update_message):
        for iu, ut in update_message:
            if ut != retico_core.UpdateType.ADD:
                continue  # COMMIT just marks end-of-utterance; nothing extra to speak
            text = (getattr(iu, "text", "") or "").strip()
            if text:
                self._queue.put(text)
        return None

    def _drain(self) -> None:
        while True:
            text = self._queue.get()
            try:
                self.say(text)
            except Exception as exc:  # one bad clause must not kill the worker
                print(f"[tts] synthesis failed for {text!r}: {exc}")
