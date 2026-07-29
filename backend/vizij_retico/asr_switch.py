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
import time
from typing import Any, Callable, Optional

import retico_core
from retico_core.text import SpeechRecognitionIU


def source_of(iu: Any) -> str:
    """Which ASR produced this IU ('whisper' | 'google' | 'browser')."""
    name = type(getattr(iu, "creator", None)).__name__
    if "Whisper" in name:
        return "whisper"
    if "Google" in name:
        return "google"
    return "browser"


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

    def __init__(
        self,
        get_source: Callable[[], str],
        is_speaking: Optional[Callable[[], bool]] = None,
        recent_spoken: Optional[Callable[[], str]] = None,
        on_barge_in: Optional[Callable[[], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.get_source = get_source
        self.is_speaking = is_speaking or (lambda: False)
        self.recent_spoken = recent_spoken or (lambda: "")
        self.on_barge_in = on_barge_in
        self._echoes = 0

    @staticmethod
    def _utterance_text(ius) -> str:
        """Reconstruct what this message says, for the echo comparison.

        A COMMIT carries the whole utterance; otherwise the ADDs are the words of the
        current hypothesis. Either way we judge the message as a unit.
        """
        for iu, ut in ius:
            if ut == retico_core.UpdateType.COMMIT:
                return getattr(iu, "get_text", lambda: "")() or ""
        return " ".join(
            (getattr(iu, "get_text", lambda: "")() or "")
            for iu, ut in ius
            if ut == retico_core.UpdateType.ADD
        )

    def process_update(self, update_message):
        from .echo import is_echo

        active = self.get_source()
        items = list(update_message)

        # Simulated turns (debug harness) always pass, whichever source is active and even
        # while speaking — the harness is how the pipeline gets tested.
        if any(getattr(iu, "simulated", False) for iu, _ in items):
            out = retico_core.UpdateMessage()
            for iu, ut in items:
                out.add_iu(iu, ut)
            return out

        items = [(iu, ut) for iu, ut in items if source_of(iu) == active]
        if not items:
            return None  # the inactive ASR is still running; drop its output

        # Decide for the whole message, never per-IU. Dropping a COMMIT while letting its
        # ADDs through leaves the downstream accumulator holding words it will never be
        # told to clear, and they get prepended to the user's next turn.
        if self.is_speaking():
            heard = self._utterance_text(items)
            if is_echo(heard, self.recent_spoken()):
                self._echoes += 1
                if self._echoes % 25 == 1:
                    print(f"[asr] ignored own voice (n={self._echoes}): {heard[:60]!r}")
                return None
            # Not our words — the user is talking over us. That is an interruption, and
            # it should stop the agent rather than be queued behind it.
            if self.on_barge_in is not None:
                print(f"[asr] barge-in: {heard[:60]!r}")
                self.on_barge_in()

        out = retico_core.UpdateMessage()
        for iu, ut in items:
            out.add_iu(iu, ut)
        return out


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
        # Pass any known source through. This used to collapse to whisper-or-browser,
        # which silently rerouted a "google" selection to the browser recognizer — the
        # UI showed Google selected while Web Speech was actually running.
        if source not in ("whisper", "google", "browser"):
            source = "browser"
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
