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

    def __init__(self, hub: WebSocketHub, sample_width: int = 2, **kwargs) -> None:
        super().__init__(**kwargs)
        self.hub = hub
        self.sample_width = sample_width

    def process_update(self, _):
        try:
            sample = self.hub.audio_in.get(timeout=1.0)
        except queue.Empty:
            return None
        rate = self.hub.audio_rate
        channels = max(1, self.hub.audio_channels)
        nframes = len(sample) // (self.sample_width * channels)
        output_iu = self.create_iu()
        output_iu.set_audio(sample, nframes, rate, self.sample_width)
        return retico_core.UpdateMessage.from_iu(output_iu, retico_core.UpdateType.ADD)
