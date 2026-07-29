"""WebInputModule — browser-captured media → retico IUs.

A producing module that drains the shared hub's inbound audio queue and emits
retico `AudioIU`s (feeding ASR + the MaAI turn-taking/backchannel/nod predictors).
Replaces retico's server-side `MicrophoneModule`: capture happens in the browser
(`getUserMedia`) and is streamed to the backend over the WebSocket.

Video → image IUs (for FER) is handled analogously once retico-vision is wired.
"""

from __future__ import annotations

import queue
import time

import retico_core
from retico_core.audio import AudioIU

from .hub import WebSocketHub


class WebInputModule(retico_core.AbstractProducingModule):
    @staticmethod
    def name() -> str:
        return "Web Input Module"

    @staticmethod
    def description() -> str:
        return "Emits AudioIUs from browser-streamed microphone audio (via the WebSocket hub)."

    @staticmethod
    def output_iu():
        return AudioIU

    def __init__(
        self,
        hub: WebSocketHub,
        sample_width: int = 2,
        frame_ms: int = 10,
        batch_ms: int = 60,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.hub = hub
        self.sample_width = sample_width
        # Re-chunk into fixed frames. The browser worklet posts 128-sample (8 ms)
        # blocks, but webrtcvad (retico-whisperasr's VAD) and retico-maai both require
        # exact 10/20/30 ms frames — so we buffer and slice to a constant frame here.
        self.frame_ms = frame_ms
        # How much audio to pack into a single UpdateMessage.
        #
        # This is a throughput fix, not a tuning knob. A consuming AbstractModule takes
        # exactly ONE UpdateMessage per left buffer per loop iteration, and that loop
        # sleeps 20 ms — so it can accept at most ~50 messages/second. Emitting one 10 ms
        # frame per message therefore delivered 0.5 s of audio per second of wall clock:
        # the ASR fell irrecoverably behind, and since the queue is unbounded it kept
        # falling behind until it was transcribing the agent's earlier replies.
        #
        # Packing 60 ms per message gives ~3 s/s of headroom. The IUs stay 10 ms so VAP
        # still gets the frame rate it needs — there are just many of them per message.
        #
        # The cost is latency: audio is held up to batch_ms before it is handed on. 60 ms
        # is the balance — enough headroom to never fall behind, less than one VAP frame
        # period (100 ms at 10 Hz) so turn-taking is not visibly delayed.
        self.batch_ms = batch_ms
        self._buf = bytearray()

    def process_update(self, _):
        # Accumulate *to a deadline* rather than draining opportunistically. This module
        # runs a tight producer loop and consumes the queue as fast as the browser fills
        # it, so at real time there is never a backlog sitting there to batch — a
        # non-blocking drain returns one 8 ms block and emits a single frame, which is
        # the starvation this is meant to fix. We have to wait to collect a batch.
        deadline = time.monotonic() + self.batch_ms / 1000.0
        try:
            self._buf.extend(self.hub.audio_in.get(timeout=1.0))
        except queue.Empty:
            return None
        target_bytes = self.hub.audio_rate * self.batch_ms // 1000 * self.sample_width
        while len(self._buf) < target_bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                self._buf.extend(self.hub.audio_in.get(timeout=remaining))
            except queue.Empty:
                break
        rate = self.hub.audio_rate
        channels = max(1, self.hub.audio_channels)
        frame_samples = rate * self.frame_ms // 1000
        frame_bytes = frame_samples * self.sample_width * channels
        if frame_bytes <= 0:
            return None

        if len(self._buf) < frame_bytes:
            return None

        update = retico_core.UpdateMessage()
        while len(self._buf) >= frame_bytes:
            frame = bytes(self._buf[:frame_bytes])
            del self._buf[:frame_bytes]
            nframes = len(frame) // (self.sample_width * channels)
            output_iu = self.create_iu()
            output_iu.set_audio(frame, nframes, rate, self.sample_width)
            update.add_iu(output_iu, retico_core.UpdateType.ADD)
        return update
