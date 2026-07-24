"""Runtime switching between the two ASR sources.

Both ASR paths can be live at once, so the choice is a routing decision rather than a
restart:

- browser  — `BrowserASRModule`, fed by the browser's Web Speech transcripts over the
             WebSocket. Cheap; no model to load.
- whisper  — `retico_whisperasr.WhisperASRModule`, transcribing the streamed audio on
             the backend. Fully local, but constructing it loads a Whisper model, so it
             is created lazily the first time the user switches to it.

`AsrGate` sits between the ASR modules and their consumers (the bridge + the LLM) and
forwards only the IUs produced by the active source, so exactly one transcript stream
reaches the dialogue graph no matter how many ASRs are running.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

import retico_core
from retico_core.text import SpeechRecognitionIU


def source_of(iu: Any) -> str:
    """Which ASR produced this IU ('whisper' | 'browser')."""
    creator = getattr(iu, "creator", None)
    return "whisper" if "Whisper" in type(creator).__name__ else "browser"


class AsrGate(retico_core.AbstractModule):
    """Passthrough that only forwards IUs from the currently active ASR source."""

    @staticmethod
    def name() -> str:
        return "ASR Gate"

    @staticmethod
    def description() -> str:
        return "Forwards SpeechRecognitionIUs from the active ASR source only."

    @staticmethod
    def input_ius():
        return [SpeechRecognitionIU]

    @staticmethod
    def output_iu():
        return SpeechRecognitionIU

    def __init__(self, get_source: Callable[[], str], **kwargs) -> None:
        super().__init__(**kwargs)
        self.get_source = get_source

    def process_update(self, update_message):
        active = self.get_source()
        out = retico_core.UpdateMessage()
        forwarded = 0
        for iu, ut in update_message:
            # Simulated turns (debug harness) always pass, whichever source is active.
            if not getattr(iu, "simulated", False) and source_of(iu) != active:
                continue  # the inactive ASR is still running; drop its output
            out.add_iu(iu, ut)
            forwarded += 1
        return out if forwarded else None


class AsrSwitcher:
    """Owns the active-source flag and lazily brings up Whisper on first use."""

    def __init__(
        self,
        hub,
        gate: AsrGate,
        web_in,
        on_status: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.hub = hub
        self.gate = gate
        self.web_in = web_in
        self.on_status = on_status
        self._whisper = None
        self._lock = threading.Lock()

    @property
    def whisper_ready(self) -> bool:
        return self._whisper is not None

    def set_source(self, source: str) -> None:
        source = "whisper" if source == "whisper" else "browser"
        if source == "whisper" and not self.whisper_ready:
            # Load off-thread: constructing WhisperASRModule pulls in a Whisper model.
            threading.Thread(target=self._start_whisper, daemon=True).start()
            self._notify("loading", "whisper")
            return
        self.hub.asr_source = source
        self._notify("active", source)

    def _start_whisper(self) -> None:
        with self._lock:
            if self._whisper is not None:
                return
            try:
                from retico_whisperasr import WhisperASRModule

                whisper = WhisperASRModule(framerate=16000, language="en", silence_dur=1)
                # Wire into the already-running network, then start just this module.
                self.web_in.subscribe(whisper)
                # NOTE: retico's add_left_buffer() calls stop() on the target module, so
                # subscribing to the live gate halts it — restart the gate afterwards or
                # no transcript reaches the dialogue graph again.
                whisper.subscribe(self.gate)
                self.gate.run(run_setup=False)
                whisper.run()
                self._whisper = whisper
            except Exception as exc:  # keep the browser path usable on failure
                print(f"[asr] failed to start Whisper: {exc}")
                self._notify("error", str(exc))
                return
        self.hub.asr_source = "whisper"
        self._notify("active", "whisper")

    def _notify(self, state: str, detail: str) -> None:
        if self.on_status is not None:
            self.on_status(state, detail)

    def stop(self) -> None:
        if self._whisper is not None:
            try:
                self._whisper.stop()
            except Exception:
                pass
