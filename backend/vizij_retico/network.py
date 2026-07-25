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
    def _status(state: str, detail: str = "") -> None:
        hub.broadcast(framer.frame("dialogue.state", {"state": state, "text": detail}))

    llm = LLMModule(
        speak=hub.say_handler,  # set in start()
        base_url=CONFIG.llm_base_url,
        model=CONFIG.llm_model,
        system=CONFIG.llm_system,
        emote=make_emote_handler(hub, framer),  # reply text -> emotion.affect
        status=_status,  # dialogue.state events for the pipeline preview
    )
    # Test harness: a simulated user turn opens the floor gate so the reply is prompt.
    hub.simulate_turn_handler = lambda: llm.notify_turn("agent_should_speak")
    # Debug harness: broadcast a cue (nod.cue, backchannel.cue, emotion.affect, …) so the
    # face behaviours can be exercised without waiting for a model to fire them.
    hub.emit_cue_handler = lambda cue, payload: hub.broadcast(framer.frame(cue, payload))
    # Feed the derived turn state to the LLM so it only replies when the floor is the
    # agent's (agent_should_speak), instead of on every ASR commit.
    classifiers = MaaiClassifiers(on_turn_state=llm.notify_turn)
    bridge = VizijWebSocketModule(hub, classifiers=classifiers.registry, framer=framer)

    # Audio streams to the backend for turn-taking/backchannel/nod regardless of ASR.
    for consumer in (turn, bc, nod):
        web_in.subscribe(consumer)
        consumer.subscribe(bridge)

    # ASR: both sources can run at once; the gate forwards only the active one's
    # transcript to the bridge (asr.text events) and the LLM (spoken reply).
    from .asr_switch import AsrGate, AsrSwitcher
    from .browser_asr import BrowserASRModule

    gate = AsrGate(get_source=lambda: hub.asr_source)
    browser_asr = BrowserASRModule(hub)  # head producer, fed by the browser via the hub
    browser_asr.subscribe(gate)
    gate.subscribe(bridge)
    gate.subscribe(llm)

    def _asr_status(state: str, detail: str) -> None:
        hub.broadcast(
            framer.frame(
                "asr.source",
                {"state": state, "source": hub.asr_source, "detail": detail},
            )
        )

    switcher = AsrSwitcher(hub, gate, web_in, on_status=_asr_status)
    hub.set_asr_source_handler = switcher.set_source
    if CONFIG.asr_source == "whisper":
        switcher.set_source("whisper")  # brings Whisper up in the background

    return web_in, [web_in, turn, bc, nod, browser_asr, gate, llm, bridge]


def start(mode: str = "fake") -> RunningNetwork:
    hub = WebSocketHub(CONFIG.host, CONFIG.port)
    hub.mode = mode
    # Start on the browser path even when whisper is configured: Whisper loads in the
    # background, and the switcher flips the source once it's actually ready (so a slow
    # or failed model load can't leave the graph with no ASR at all).
    hub.asr_source = "browser"
    # Descriptor for the debug pipeline preview: what's wired at each stage.
    if mode == "maai":
        hub.pipeline = {
            "mode": "maai",
            "capture": "browser mic · 16 kHz PCM",
            "turn_taking": "retico-maai VAP",
            "backchannel": True,
            "nod": True,
            "asr_options": ["browser", "whisper"],  # switchable at runtime
            "llm": {"model": CONFIG.llm_model or "auto-detect", "gated_on_turn": True},
            "tts": "gTTS",
            "lipsync": "amplitude (jaw_open); visemes available, not wired",
        }
    else:
        hub.pipeline = {"mode": "fake", "turn_taking": "synthetic (FakeTurnModule)", "tts": "gTTS"}
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
