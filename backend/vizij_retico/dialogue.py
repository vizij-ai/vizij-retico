"""LLM dialogue: committed ASR transcript -> reply -> TTS.

Talks to any OpenAI-compatible chat endpoint. Default is LM Studio
(http://localhost:1234/v1); point `LLM_BASE_URL`/`LLM_MODEL` at a cloud provider
later for better quality. Replies are spoken via the provided `speak` callback
(the hub's gTTS say-handler), so they flow out as speech.audio and lip-sync.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, Optional

import requests
import retico_core
from retico_core.text import SpeechRecognitionIU

# Strip reasoning blocks that "thinking" models (e.g. Qwen3) may emit, so they never
# reach TTS.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def resolve_model(base_url: str, configured: str) -> Optional[str]:
    if configured:
        return configured
    try:
        r = requests.get(f"{base_url}/models", timeout=5)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0]["id"] if data else None
    except Exception:
        return None


def chat(base_url: str, model: str, messages: list[dict], timeout: float = 60.0) -> str:
    r = requests.post(
        f"{base_url}/chat/completions",
        json={"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 120},
        timeout=timeout,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return _THINK_RE.sub("", content).strip()


class LLMModule(retico_core.AbstractConsumingModule):
    """Consumes committed ASR text, generates a reply, and speaks it."""

    @staticmethod
    def name() -> str:
        return "LLM Dialogue Module"

    @staticmethod
    def description() -> str:
        return "Turns committed ASR transcripts into spoken replies via an OpenAI-compatible LLM."

    @staticmethod
    def input_ius():
        return [SpeechRecognitionIU]

    # Turn states (from the VAP turn-taking model) in which the agent may take the floor.
    GO_STATES = frozenset({"agent_should_speak"})

    def __init__(
        self,
        speak: Callable[[str], None],
        base_url: str,
        model: str = "",
        system: str = "",
        cooldown: float = 3.0,
        gate_on_turn: bool = True,
        max_wait: float = 4.0,
        emote: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.speak = speak
        # Optional: derive + broadcast the agent's affect from the reply (face expression).
        self.emote = emote
        self.base_url = base_url.rstrip("/")
        self.configured_model = model
        self.system = system
        self.cooldown = cooldown
        # Wait for the turn-taking model to yield the floor before replying, rather than
        # replying the instant ASR commits. max_wait bounds the wait so a reply always
        # comes even if the model never emits a clean shift.
        self.gate_on_turn = gate_on_turn
        self.max_wait = max_wait
        self._tokens: list[str] = []
        self._history: list[dict] = []
        self._model: Optional[str] = None
        self._busy = False
        self._muted_until = 0.0
        # Transcript waiting for the agent's turn (guarded by _lock; notify_turn is
        # called from the bridge thread while process_update runs on the ASR thread).
        self._pending: Optional[str] = None
        self._released = False  # gate opened (turn yielded or max_wait elapsed)
        self._turn_state = ""
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def process_update(self, update_message):
        for iu, ut in update_message:
            token = (getattr(iu, "text", "") or "").strip()
            if ut == retico_core.UpdateType.ADD:
                if token:
                    self._tokens.append(token)
            elif ut == retico_core.UpdateType.COMMIT:
                text = " ".join(self._tokens).strip()
                self._tokens = []
                if text:
                    self._enqueue(text)
        return None

    def notify_turn(self, state: str) -> None:
        """Called by the turn-taking classifier on each turn.state. Opens the gate once
        the floor is the agent's; then tries to reply."""
        with self._lock:
            self._turn_state = state
            if self._pending is None or state not in self.GO_STATES:
                return
            self._released = True
        self._try()

    def _enqueue(self, text: str) -> None:
        with self._lock:
            self._pending = text
            self._released = (not self.gate_on_turn) or self._turn_state in self.GO_STATES
            # Bound the wait: reply even if the turn model never emits a clean shift.
            # A self-contained timer means the gate doesn't depend on the VAP heartbeat.
            self._arm_locked(0.0 if self._released else self.max_wait)
        self._try()

    def _wake(self) -> None:
        """Timer callback: open the gate (max_wait elapsed) and retry."""
        with self._lock:
            if self._pending is not None:
                self._released = True
        self._try()

    def _arm_locked(self, delay: float) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(max(0.0, delay), self._wake)
        self._timer.daemon = True
        self._timer.start()

    def _try(self) -> None:
        """Fire the pending reply if the gate is open and we're not busy/cooling down;
        otherwise re-arm to retry once the block clears."""
        with self._lock:
            if self._pending is None or not self._released:
                return
            now = time.monotonic()
            if self._busy or now < self._muted_until:
                # Blocked by an in-flight reply or the post-reply cooldown — retry later.
                self._arm_locked((self._muted_until - now) if now < self._muted_until else 0.25)
                return
            text = self._pending
            self._pending = None
            self._released = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._busy = True
        threading.Thread(target=self._reply, args=(text,), daemon=True).start()

    def _reply(self, text: str) -> None:
        try:
            if self._model is None:
                self._model = resolve_model(self.base_url, self.configured_model)
            if not self._model:
                print("[llm] no model — is LM Studio running with a model loaded on", self.base_url, "?")
                return
            self._history.append({"role": "user", "content": text})
            messages = ([{"role": "system", "content": self.system}] if self.system else [])
            messages += self._history[-8:]
            reply = chat(self.base_url, self._model, messages)
            print(f"[llm] user={text!r} -> {reply!r}")
            if not reply:
                # Empty after stripping (e.g. a thinking model that only reasoned) —
                # don't feed "" to TTS; leave history untouched so the next turn retries.
                print("[llm] empty reply — skipping speak (is the model in thinking mode?)")
                return
            self._history.append({"role": "assistant", "content": reply})
            # Express affect just before speaking so the face is set as the audio starts.
            if self.emote is not None:
                self.emote(reply)
            self.speak(reply)
            self._muted_until = time.monotonic() + self.cooldown + len(reply) / 12.0
        except Exception as exc:
            print(f"[llm] error: {exc}")
        finally:
            self._busy = False
            # A transcript may have queued up while we were replying — retry it (it will
            # respect the cooldown window we just set).
            self._try()
