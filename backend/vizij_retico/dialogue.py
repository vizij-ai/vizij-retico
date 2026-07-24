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

    def __init__(
        self,
        speak: Callable[[str], None],
        base_url: str,
        model: str = "",
        system: str = "",
        cooldown: float = 3.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.speak = speak
        self.base_url = base_url.rstrip("/")
        self.configured_model = model
        self.system = system
        self.cooldown = cooldown
        self._tokens: list[str] = []
        self._history: list[dict] = []
        self._model: Optional[str] = None
        self._busy = False
        self._muted_until = 0.0

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
                    self._maybe_reply(text)
        return None

    def _maybe_reply(self, text: str) -> None:
        # Skip while a reply is in flight or during the post-reply cooldown (avoids
        # replying to the agent's own TTS bleeding into the mic).
        if self._busy or time.time() < self._muted_until:
            return
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
            self.speak(reply)
            self._muted_until = time.time() + self.cooldown + len(reply) / 12.0
        except Exception as exc:
            print(f"[llm] error: {exc}")
        finally:
            self._busy = False
