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

    from .affect import make_emote_handler
    from .classifiers import MaaiClassifiers
    from .dialogue import LLMModule
    from .web_input import WebInputModule

    web_in = WebInputModule(hub)
    turn = TurnTakingModule(mode="vap_mc", lang="en", frame_rate=10)
    bc = BackchannelModule(lang="en", frame_rate=10)
    nod = NodPredictionModule(lang="en", frame_rate=10)
    # committed transcript -> LLM reply -> spoken via the hub's TTS say-handler
    llm = LLMModule(
        speak=hub.say_handler,  # set in start()
        base_url=CONFIG.llm_base_url,
        model=CONFIG.llm_model,
        system=CONFIG.llm_system,
        emote=make_emote_handler(hub, framer),  # reply text -> emotion.affect
    )
    # Feed the derived turn state to the LLM so it only replies when the floor is the
    # agent's (agent_should_speak), instead of on every ASR commit.
    classifiers = MaaiClassifiers(on_turn_state=llm.notify_turn)
    bridge = VizijWebSocketModule(hub, classifiers=classifiers.registry, framer=framer)

    # Audio streams to the backend for turn-taking/backchannel/nod regardless of ASR.
    for consumer in (turn, bc, nod):
        web_in.subscribe(consumer)
        consumer.subscribe(bridge)

    # ASR: transcript -> bridge (asr.text events) + llm (spoken reply). Pick the source.
    if CONFIG.asr_source == "whisper":
        from retico_whisperasr import WhisperASRModule

        asr = WhisperASRModule(framerate=16000, language="en", silence_dur=1)
        web_in.subscribe(asr)  # Whisper transcribes the streamed audio on the backend
    else:
        from .browser_asr import BrowserASRModule

        asr = BrowserASRModule(hub)  # a head producer, fed by the browser via the hub
    asr.subscribe(bridge)
    asr.subscribe(llm)

    return web_in, [web_in, turn, bc, nod, asr, llm, bridge]


def start(mode: str = "fake") -> RunningNetwork:
    hub = WebSocketHub(CONFIG.host, CONFIG.port)
    hub.mode = mode
    hub.asr_source = CONFIG.asr_source
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
