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

from . import providers
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


def _build_lite(hub: WebSocketHub, framer: EventFramer):
    """Dialogue without on-device perception: browser ASR -> LLM -> TTS -> face.

    No torch, no VAP, no local Whisper — this is what the small container ships. The
    cost is that there is no turn-taking model, so the LLM's floor gate has nothing to
    wait for and is disabled; replies fire as soon as a transcript commits.
    """
    from .affect import AFFECT_INSTRUCTION, AffectModule
    from .browser_asr import BrowserASRModule
    from .classifiers import MaaiClassifiers
    from .dialogue import LLMModule
    from .tts_module import TTSModule

    def _status(state: str, detail: str = "") -> None:
        hub.broadcast(framer.frame("dialogue.state", {"state": state, "text": detail}))

    llm = LLMModule(
        base_url=CONFIG.llm_base_url,
        model=CONFIG.llm_model,
        system=CONFIG.llm_system + AFFECT_INSTRUCTION,
        status=_status,
        gate_on_turn=False,  # nothing produces turn.state in this profile
    )
    tts = TTSModule(say=hub.say_handler)
    bridge = VizijWebSocketModule(hub, classifiers=MaaiClassifiers().registry, framer=framer)

    # Two ASR sources feed a gate that forwards only the active one — the same shape as
    # the maai profile, so switching behaves identically in both. Google STT needs the
    # audio itself, which this profile previously had no consumer for at all.
    from .asr_switch import AsrGate
    from .google_asr import GoogleASRModule
    from .web_input import WebInputModule

    gate = AsrGate(get_source=lambda: hub.asr_source,
                    speaking_until=lambda: hub.speaking_until)
    browser_asr = BrowserASRModule(hub)
    browser_asr.subscribe(gate)

    web_in = WebInputModule(hub)
    google_asr = GoogleASRModule()
    web_in.subscribe(google_asr)
    google_asr.subscribe(gate)

    gate.subscribe(bridge)
    gate.subscribe(llm)
    llm.subscribe(tts)
    affect = AffectModule()
    llm.subscribe(affect)
    affect.subscribe(bridge)

    # FER needs no torch, so the small profile perceives the user too.
    from .fer import BrowserFERModule, FerGate

    fer_gate = FerGate(get_source=lambda: hub.fer_source)
    browser_fer = BrowserFERModule(hub)
    browser_fer.subscribe(fer_gate)
    fer_gate.subscribe(bridge)

    hub.simulate_turn_handler = lambda: None  # no floor gate to open
    hub.emit_cue_handler = lambda cue, payload: hub.broadcast(framer.frame(cue, payload))

    def _set_provider(kind: str, provider_id: str) -> None:
        spec = providers.get(kind, provider_id)
        if spec is None or not spec.available:
            return
        if kind == "llm":
            llm.set_provider(provider_id, spec.settings)
        elif kind == "tts":
            hub.tts_provider = provider_id
            # A voice belongs to one provider, so carrying the old selection across a
            # switch would leave e.g. "Joanna" selected while gTTS is speaking.
            providers.set_active_tts(provider_id)
            hub.voice = providers.default_voice(provider_id)
            hub.active_providers["voice"] = hub.voice
        elif kind == "voice":
            hub.voice = provider_id
        elif kind == "asr":
            # Both sources stay live; the gate decides which reaches the graph.
            hub.asr_source = provider_id
            hub.broadcast(
                framer.frame(
                    "asr.source",
                    {"state": "active", "source": provider_id, "detail": spec.label},
                )
            )
        elif kind == "turn":
            llm.set_gating(provider_id == "vap")
        else:
            return
        hub.active_providers[kind] = provider_id
        hub.broadcast(
            framer.frame("provider.state", {"kind": kind, "id": provider_id, "state": "active"})
        )

    hub.set_provider_handler = _set_provider
    hub.set_asr_source_handler = lambda source: _set_provider("asr", source)
    llm_spec = providers.get("llm", CONFIG.llm_provider) or providers.get("llm", "lmstudio")
    if llm_spec is not None:
        llm.set_provider(llm_spec.id, llm_spec.settings)
        hub.active_providers["llm"] = llm_spec.id

    return browser_asr, [
        web_in, google_asr, browser_asr, gate, browser_fer, fer_gate,
        llm, tts, affect, bridge,
    ]


def _build_maai(hub: WebSocketHub, framer: EventFramer):
    # Imported lazily so the fake path never needs torch/maai installed.
    from retico_maai import TurnTakingModule, BackchannelModule, NodPredictionModule

    from .affect import AFFECT_INSTRUCTION, AffectModule
    from .classifiers import MaaiClassifiers
    from .dialogue import LLMModule
    from .tts_module import TTSModule
    from .web_input import WebInputModule

    web_in = WebInputModule(hub)
    turn = TurnTakingModule(mode="vap_mc", lang="en", frame_rate=10)
    bc = BackchannelModule(lang="en", frame_rate=10)
    nod = NodPredictionModule(lang="en", frame_rate=10)
    # committed transcript -> LLM reply -> spoken via the hub's TTS say-handler
    def _status(state: str, detail: str = "") -> None:
        hub.broadcast(framer.frame("dialogue.state", {"state": state, "text": detail}))

    llm = LLMModule(
        base_url=CONFIG.llm_base_url,
        model=CONFIG.llm_model,
        system=CONFIG.llm_system + AFFECT_INSTRUCTION,
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

    from .google_asr import GoogleASRModule

    gate = AsrGate(get_source=lambda: hub.asr_source,
                    speaking_until=lambda: hub.speaking_until)
    browser_asr = BrowserASRModule(hub)  # head producer, fed by the browser via the hub
    browser_asr.subscribe(gate)
    # Google STT reads the same streamed audio the turn-taking models do.
    google_asr = GoogleASRModule()
    web_in.subscribe(google_asr)
    google_asr.subscribe(gate)
    gate.subscribe(bridge)
    gate.subscribe(llm)
    # Streamed clauses -> speech, spoken in generation order.
    tts = TTSModule(say=hub.say_handler)  # say_handler is set in start()
    llm.subscribe(tts)
    # Affect is a first-class IU rather than a side-channel broadcast, so it can be
    # revised as better evidence arrives and other modules can subscribe to it.
    affect = AffectModule()
    llm.subscribe(affect)
    affect.subscribe(bridge)


    # --- FER: perceiving the user -------------------------------------------
    from .fer import BrowserFERModule, FerGate, FerSwitcher

    def _fer_status(state: str, detail: str) -> None:
        hub.broadcast(
            framer.frame("fer.source", {"state": state, "source": hub.fer_source, "detail": detail})
        )

    fer_gate = FerGate(get_source=lambda: hub.fer_source)
    browser_fer = BrowserFERModule(hub)
    browser_fer.subscribe(fer_gate)
    fer_gate.subscribe(bridge)
    fer_switcher = FerSwitcher(hub, fer_gate, on_status=_fer_status)

    def _asr_status(state: str, detail: str) -> None:
        hub.broadcast(
            framer.frame(
                "asr.source",
                {"state": state, "source": hub.asr_source, "detail": detail},
            )
        )

    switcher = AsrSwitcher(hub, gate, web_in, on_status=_asr_status)
    hub.set_asr_source_handler = switcher.set_source

    # --- provider switching (asr | llm | tts) --------------------------------
    def _set_provider(kind: str, provider_id: str) -> None:
        spec = providers.get(kind, provider_id)
        if spec is None:
            print(f"[providers] unknown {kind} provider {provider_id!r}")
            return
        if not spec.available:
            hub.broadcast(
                framer.frame(
                    "provider.state",
                    {"kind": kind, "id": provider_id, "state": "unavailable", "detail": spec.note},
                )
            )
            return
        if kind == "asr":
            switcher.set_source(provider_id)  # emits its own asr.source events
            return
        if kind == "fer":
            fer_switcher.set_source(provider_id)
            return
        if kind == "llm":
            llm.set_provider(provider_id, spec.settings)
        elif kind == "tts":
            hub.tts_provider = provider_id
            providers.set_active_tts(provider_id)
            hub.voice = providers.default_voice(provider_id)
            hub.active_providers["voice"] = hub.voice
        elif kind == "voice":
            hub.voice = provider_id
        elif kind == "turn":
            llm.set_gating(provider_id == "vap")
        else:
            return
        hub.active_providers[kind] = provider_id
        hub.pipeline["providers"] = providers.describe(hub.active_providers)
        hub.broadcast(
            framer.frame("provider.state", {"kind": kind, "id": provider_id, "state": "active"})
        )

    hub.set_provider_handler = _set_provider
    # Apply the configured LLM provider (falls back to lmstudio if e.g. no Gemini key).
    llm_spec = providers.get("llm", CONFIG.llm_provider)
    if llm_spec is None or not llm_spec.available:
        if llm_spec is not None:
            print(f"[providers] llm {CONFIG.llm_provider!r} unavailable ({llm_spec.note}); using lmstudio")
        llm_spec = providers.get("llm", "lmstudio")
    if llm_spec is not None:
        llm.set_provider(llm_spec.id, llm_spec.settings)
        hub.active_providers["llm"] = llm_spec.id

    if CONFIG.asr_source == "whisper":
        switcher.set_source("whisper")  # brings Whisper up in the background

    return web_in, [
        web_in, turn, bc, nod, browser_asr, google_asr, gate, browser_fer, fer_gate,
        llm, tts, affect, bridge,
    ]


def start(mode: str = "fake") -> RunningNetwork:
    # "full" is the container profile name for the on-device perception build.
    mode = "maai" if mode == "full" else mode
    hub = WebSocketHub(CONFIG.host, CONFIG.port)
    hub.mode = mode
    # Whisper is the exception to honouring CONFIG here: it loads in the background, and
    # the switcher flips the source once it's actually ready, so a slow or failed model
    # load can't leave the graph with no ASR at all. Google STT and browser are both
    # ready immediately. Fall back if the configured source isn't usable in this build.
    wanted = CONFIG.asr_source
    if wanted == "whisper":
        hub.asr_source = "browser"
    else:
        spec = providers.get("asr", wanted)
        hub.asr_source = wanted if (spec and spec.available) else "browser"
        if hub.asr_source != wanted:
            print(f"[asr] {wanted} unavailable, starting on browser")
    hub.tts_provider = CONFIG.tts_provider
    providers.set_active_tts(CONFIG.tts_provider)
    hub.voice = providers.default_voice(CONFIG.tts_provider)
    hub.fer_source = CONFIG.fer_source
    # "turn" reflects the graph actually built: only the maai profile has VAP modules,
    # so lite starts (and stays) ungated regardless of what is installed.
    hub.active_providers = {
        "asr": hub.asr_source,
        "turn": "vap" if mode == "maai" else "off",
        "voice": providers.default_voice(CONFIG.tts_provider),
        "fer": hub.fer_source,
        "llm": CONFIG.llm_provider,
        "tts": CONFIG.tts_provider,
    }
    # Descriptor for the debug pipeline preview: what's wired at each stage.
    if mode == "maai":
        hub.pipeline = {
            "mode": "maai",
            "capture": "browser mic · 16 kHz PCM",
            "turn_taking": "retico-maai VAP",
            "backchannel": True,
            "fer": True,
            "nod": True,
            "asr_options": ["google", "browser", "whisper"],  # switchable at runtime
            "llm": {"model": CONFIG.llm_model or "auto-detect", "gated_on_turn": True},
            "tts": CONFIG.tts_provider,
            "lipsync": "amplitude (jaw_open); visemes available, not wired",
            # Full registry (options + availability) for the provider selector.
            "providers": providers.describe(hub.active_providers),
        }
    elif mode == "lite":
        hub.pipeline = {
            "mode": "lite",
            "asr_options": ["google", "browser"],
            "llm": {"model": CONFIG.llm_model or "auto-detect", "gated_on_turn": False},
            "tts": CONFIG.tts_provider,
            "lipsync": "visemes (Polly) or amplitude (gTTS)",
            "providers": providers.describe(hub.active_providers),
        }
    else:
        hub.pipeline = {"mode": "fake", "turn_taking": "synthetic (FakeTurnModule)", "tts": "gTTS"}
    framer = EventFramer()  # shared by the bridge and the TTS say-handler
    hub.say_handler = make_say_handler(hub, framer)
    hub.start()
    builder = {"fake": _build_fake, "lite": _build_lite}.get(mode, _build_maai)
    head, modules = builder(hub, framer)
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
