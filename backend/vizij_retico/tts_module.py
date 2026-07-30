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
        self._queue: "queue.Queue[tuple[int, str]]" = queue.Queue()
        # Bumped on cancel. Queued clauses carry the generation they were enqueued in, so
        # anything from a superseded reply is discarded instead of spoken after the
        # interruption. Cheaper and less racy than draining the queue, which cannot
        # recall a clause the worker has already taken.
        self._generation = 0
        # Generation the reply currently streaming belongs to.
        self._reply_generation = 0
        self._worker = threading.Thread(target=self._drain, daemon=True)
        self._worker.start()

    def process_update(self, update_message):
        for iu, ut in update_message:
            if ut != retico_core.UpdateType.ADD:
                continue  # COMMIT just marks end-of-utterance; nothing extra to speak
            text = (getattr(iu, "text", "") or "").strip()
            if not text:
                continue
            # Tag with the generation the *reply* began in, not the one current at enqueue
            # time. The LLM keeps streaming for a moment after a barge-in cancels, and
            # those late clauses were being stamped with the new generation — so the
            # interrupted reply carried on speaking alongside the new one. Two voices,
            # different sentences.
            self._queue.put((self._reply_generation, text))
        return None

    def begin_reply(self) -> None:
        """Called when a new reply starts, to bind its clauses to the live generation."""
        self._reply_generation = self._generation

    def cancel(self) -> None:
        """Abandon everything queued, and anything still streaming from this reply."""
        self._generation += 1
        # Also move the in-flight reply forward, so clauses that arrive after this point
        # from the *interrupted* generation are discarded rather than inheriting the new
        # one. begin_reply() re-binds when the next reply actually starts.
        self._reply_generation = -1
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _drain(self) -> None:
        while True:
            generation, text = self._queue.get()
            if generation != self._generation:
                continue  # superseded by a barge-in
            try:
                self.say(text)
            except Exception as exc:  # one bad clause must not kill the worker
                print(f"[tts] synthesis failed for {text!r}: {exc}")
