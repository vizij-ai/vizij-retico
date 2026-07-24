"""Build and run the retico network + the WebSocket hub.

Two modes:
- "fake": FakeTurnModule → VizijWebSocketModule. No torch/models; proves the bridge.
- "maai": WebInputModule → {TurnTaking, Backchannel, Nod} → VizijWebSocketModule.
          Needs retico-maai (torch + HF model download on first run).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import retico_core

from .config import CONFIG
from .events import EventFramer
from .hub import WebSocketHub
from .speech import make_say_handler
from .ws_module import VizijWebSocketModule


@dataclass
class RunningNetwork:
    hub: WebSocketHub
    head: Any
    modules: list = field(default_factory=list)

    def stop(self) -> None:
        try:
            retico_core.network.stop(self.head)
        finally:
            self.hub.stop()


def _build_fake(hub: WebSocketHub, framer: EventFramer):
    from .testing import FakeTurnModule, FAKE_CLASSIFIERS

    fake = FakeTurnModule()
    bridge = VizijWebSocketModule(hub, classifiers=FAKE_CLASSIFIERS, framer=framer)
    fake.subscribe(bridge)
    return fake, [fake, bridge]


def _build_maai(hub: WebSocketHub, framer: EventFramer):
    # Imported lazily so the fake path never needs torch/maai installed.
    from retico_maai import TurnTakingModule, BackchannelModule, NodPredictionModule
    from retico_whisperasr import WhisperASRModule

    from .classifiers import MaaiClassifiers
    from .web_input import WebInputModule

    web_in = WebInputModule(hub)
    turn = TurnTakingModule(mode="vap_mc", lang="en", frame_rate=10)
    bc = BackchannelModule(lang="en", frame_rate=10)
    nod = NodPredictionModule(lang="en", frame_rate=10)
    asr = WhisperASRModule(framerate=16000, language="en", silence_dur=1)
    bridge = VizijWebSocketModule(hub, classifiers=MaaiClassifiers().registry, framer=framer)

    for consumer in (turn, bc, nod, asr):
        web_in.subscribe(consumer)
        consumer.subscribe(bridge)

    return web_in, [web_in, turn, bc, nod, asr, bridge]


def start(mode: str = "fake") -> RunningNetwork:
    hub = WebSocketHub(CONFIG.host, CONFIG.port)
    hub.mode = mode
    framer = EventFramer()  # shared by the bridge and the TTS say-handler
    hub.say_handler = make_say_handler(hub, framer)
    hub.start()
    head, modules = _build_fake(hub, framer) if mode == "fake" else _build_maai(hub, framer)
    retico_core.network.run(head)
    return RunningNetwork(hub=hub, head=head, modules=modules)


def run_forever(mode: str = "fake") -> None:
    net = start(mode)
    print(f"[vizij-retico] network running (mode={mode}) on ws://{CONFIG.host}:{CONFIG.port}/ws")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        net.stop()
