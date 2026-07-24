"""WebInputModule — browser-captured media → retico IUs.

A producing module that drains the shared hub's inbound audio queue and emits
retico `AudioIU`s (feeding ASR + the MaAI turn-taking/backchannel/nod predictors).
Replaces retico's server-side `MicrophoneModule`: capture happens in the browser
(`getUserMedia`) and is streamed to the backend over the WebSocket.

Video → image IUs (for FER) is handled analogously once retico-vision is wired.
"""

from __future__ import annotations

import queue

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
        self, hub: WebSocketHub, sample_width: int = 2, frame_ms: int = 10, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.hub = hub
        self.sample_width = sample_width
        # Re-chunk into fixed frames. The browser worklet posts 128-sample (8 ms)
        # blocks, but webrtcvad (retico-whisperasr's VAD) and retico-maai both require
        # exact 10/20/30 ms frames — so we buffer and slice to a constant frame here.
        self.frame_ms = frame_ms
        self._buf = bytearray()

    def process_update(self, _):
        try:
            sample = self.hub.audio_in.get(timeout=1.0)
        except queue.Empty:
            return None
        rate = self.hub.audio_rate
        channels = max(1, self.hub.audio_channels)
        frame_samples = rate * self.frame_ms // 1000
        frame_bytes = frame_samples * self.sample_width * channels
        if frame_bytes <= 0:
            return None

        self._buf.extend(sample)
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
