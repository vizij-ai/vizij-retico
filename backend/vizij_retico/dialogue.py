"""LLM dialogue: committed ASR transcript -> reply -> TTS.

Talks to any OpenAI-compatible chat endpoint. Default is LM Studio
(http://localhost:1234/v1); point `LLM_BASE_URL`/`LLM_MODEL` at a cloud provider
later for better quality. Replies are spoken via the provided `speak` callback
(the hub's gTTS say-handler), so they flow out as speech.audio and lip-sync.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Callable, Optional

import requests
import retico_core
from retico_core.text import GeneratedTextIU, SpeechRecognitionIU

# Where to break a streamed reply into speakable clauses. Prefer sentence boundaries —
# each synthesized chunk is a separate audio file, so splitting mid-sentence makes the
# delivery sound chopped. Commas are only a fallback for a sentence that runs long
# enough that waiting for the full stop would delay speech.
_SENTENCE_END = re.compile(r"[.!?;:]\s")
MIN_CLAUSE_CHARS = 24
LONG_CLAUSE_CHARS = 110

# Optional affect tag the model is asked to put at the start of its reply, e.g.
# "[happy] Good morning!". Stripped before the text reaches TTS.
_AFFECT_TAG = re.compile(r"^\s*\[([A-Za-z]+)\]\s*")


def _split_point(buf: str) -> Optional[int]:
    """Index to cut `buf` at, or None to keep buffering."""
    match = _SENTENCE_END.search(buf)
    if match and match.end() >= MIN_CLAUSE_CHARS:
        return match.end()
    if len(buf) >= LONG_CLAUSE_CHARS:
        comma = buf.rfind(", ")
        if comma >= MIN_CLAUSE_CHARS:
            return comma + 2
    return None

# Strip reasoning blocks that "thinking" models (e.g. Qwen3) may emit, so they never
# reach TTS. The second pattern catches a block that was cut off before its closing tag
# (the token budget ran out mid-thought) — everything from <think> on is reasoning.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK_RE = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


# Models ignore "no emojis" in the system prompt often enough that it has to be enforced
# in code: TTS reads them aloud by name ("smiley face emoji"), which is worse than
# useless in speech. Covers pictographs, dingbats, flags, arrows, plus the ZWJ and
# variation selectors that glue multi-codepoint sequences together (and would otherwise
# be left behind as fragments when a sequence is split across stream chunks).
_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\U00002600-\U000027bf"
    "\U0001f1e6-\U0001f1ff"
    "\U00002190-\U000021ff"
    "\U00002b00-\U00002bff"
    "\U0000fe00-\U0000fe0f"
    "\U0000200d"
    "]+"
)


def clean_reply(content: str) -> str:
    text = _OPEN_THINK_RE.sub("", _THINK_RE.sub("", content or ""))
    text = _EMOJI_RE.sub("", text)
    # Stripping mid-sentence emoji leaves double spaces and " ." artefacts.
    text = re.sub(r"\s+([.!?,;:])", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _join(base_url: str, path: str) -> str:
    """Gemini's base_url must keep its trailing slash, so join defensively."""
    return f"{base_url.rstrip('/')}/{path}"


def resolve_model(base_url: str, configured: str, api_key: str = "") -> Optional[str]:
    if configured:
        return configured
    try:
        r = requests.get(_join(base_url, "models"), headers=_auth(api_key), timeout=5)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0]["id"] if data else None
    except Exception:
        return None


def chat_stream(
    base_url: str,
    model: str,
    messages: list[dict],
    timeout: float = 60.0,
    max_tokens: int = 300,
    api_key: str = "",
    extra_body: Optional[dict] = None,
):
    """Yield reply text incrementally from a streamed chat completion.

    Streaming is what makes the dialogue *incremental*: the first clause can be spoken
    while the rest is still being generated, instead of waiting for the whole reply.
    """
    r = requests.post(
        _join(base_url, "chat/completions"),
        headers=_auth(api_key),
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": True,
            **(extra_body or {}),
        },
        timeout=timeout,
        stream=True,
    )
    r.raise_for_status()
    for raw in r.iter_lines():
        if not raw:
            continue
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            delta = json.loads(data)["choices"][0].get("delta") or {}
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
        # Same reasoning-channel quirk as the non-streaming path (LM Studio + Qwen3).
        piece = delta.get("content") or delta.get("reasoning_content") or ""
        if piece:
            yield piece


def chat(
    base_url: str,
    model: str,
    messages: list[dict],
    timeout: float = 60.0,
    max_tokens: int = 300,
    api_key: str = "",
    extra_body: Optional[dict] = None,
) -> str:
    r = requests.post(
        _join(base_url, "chat/completions"),
        headers=_auth(api_key),
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": max_tokens,
            **(extra_body or {}),
        },
        timeout=timeout,
    )
    r.raise_for_status()
    message = r.json()["choices"][0]["message"]
    reply = clean_reply(message.get("content"))
    if not reply:
        # LM Studio routes a reasoning model's output into `reasoning_content`. With
        # Qwen3 + /no_think the model often answers entirely inside that channel, leaving
        # `content` empty — the reply is there, so use it rather than dropping the turn.
        reply = clean_reply(message.get("reasoning_content") or message.get("reasoning"))
    return reply


class LLMModule(retico_core.AbstractModule):
    """Committed ASR text in, incremental reply text out.

    Produces `GeneratedTextIU`s clause by clause as the model streams, so a downstream
    TTS module can start speaking before generation has finished — the dialogue itself
    is incremental, not just the perception.
    """

    @staticmethod
    def name() -> str:
        return "LLM Dialogue Module"

    @staticmethod
    def description() -> str:
        return "Streams replies to committed ASR transcripts via an OpenAI-compatible LLM."

    @staticmethod
    def input_ius():
        return [SpeechRecognitionIU]

    @staticmethod
    def output_iu():
        return GeneratedTextIU

    # Turn states (from the VAP turn-taking model) in which the agent may take the floor.
    GO_STATES = frozenset({"agent_should_speak"})

    def __init__(
        self,
        base_url: str,
        model: str = "",
        system: str = "",
        cooldown: float = 0.5,
        gate_on_turn: bool = True,
        max_wait: float = 4.0,
        status: Optional[Callable[[str, str], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.provider_id = ""
        self._last_out = None  # previous outgoing IU, for the incremental chain
        self.api_key = ""
        # "key" = static bearer from settings; "adc" = short-lived Google token minted per
        # request (Vertex). See _bearer().
        self.auth_mode = "key"
        # Provider-specific request fields merged into the chat body (Vertex uses this to
        # switch off thinking).
        self.extra_body: dict = {}
        # Appended to the system prompt for providers that need control tokens (Qwen3's
        # "/no_think"); kept out of the base persona so cloud models never see them.
        self.system_suffix = ""
        # Affect the model declared for the current reply (parsed from its leading tag);
        # attached to the first clause IU for AffectModule to pick up.
        self._affect: Optional[str] = None
        # Optional: report dialogue state (waiting_for_turn | thinking | spoke) for the
        # debug pipeline preview.
        self.status = status
        self.base_url = base_url.rstrip("/")
        self.configured_model = model
        self.system = system
        self.cooldown = cooldown
        # Wait for the turn-taking model to yield the floor before replying, rather than
        # replying the instant ASR commits. max_wait bounds the wait so a reply always
        # comes even if the model never emits a clean shift.
        self.gate_on_turn = gate_on_turn
        self.max_wait = max_wait
        self._ius: list = []  # IUs of the in-progress utterance (REVOKE-aware)
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

    def set_provider(self, provider_id: str, settings: dict) -> None:
        """Point the module at a different OpenAI-compatible endpoint at runtime.

        Clears the resolved model so the new provider's model is picked up, and drops the
        conversation history — it belongs to the previous model's context.
        """
        with self._lock:
            self.provider_id = provider_id
            self.base_url = str(settings.get("base_url", self.base_url)).rstrip("/")
            self.configured_model = str(settings.get("model", "") or "")
            self.api_key = str(settings.get("api_key", "") or "")
            self.auth_mode = str(settings.get("auth", "key") or "key")
            self.extra_body = dict(settings.get("extra_body") or {})
            self.system_suffix = str(settings.get("system_suffix", "") or "")
            self._model = None
            self._history = []
        print(f"[llm] provider -> {provider_id} ({self.base_url}, model={self.configured_model or 'auto'})")

    def _bearer(self) -> str:
        """The Authorization value for this request.

        Vertex tokens expire in about an hour, so they are minted per call rather than
        captured at switch time — otherwise a long-running instance starts 401ing mid
        session, which looks like a permissions bug rather than an expiry.
        """
        if self.auth_mode != "adc":
            return self.api_key
        from . import gcp_auth

        try:
            return gcp_auth.token()
        except Exception as exc:
            print(f"[llm] ADC token error: {exc}")
            return ""

    def _system_prompt(self) -> str:
        return f"{self.system}{self.system_suffix}" if self.system else ""

    def process_update(self, update_message):
        for iu, ut in update_message:
            if ut == retico_core.UpdateType.ADD:
                self._ius.append(iu)
            elif ut == retico_core.UpdateType.REVOKE:
                # Whisper revises hypotheses by REVOKEing superseded token IUs; keeping
                # them would feed the LLM a duplicated, garbled transcript.
                self._ius = [held for held in self._ius if held is not iu]
            elif ut == retico_core.UpdateType.COMMIT:
                text = " ".join(
                    t
                    for t in ((getattr(i, "text", "") or "").strip() for i in self._ius)
                    if t
                )
                self._ius = []
                if text:
                    self._enqueue(text)
        return None

    def set_gating(self, enabled: bool) -> None:
        """Turn the floor gate on or off at runtime.

        The difference this makes is the point of the turn-taking model, so it belongs in
        the UI rather than baked into a build: gated, the agent waits until VAP says the
        floor is its own; ungated, it replies the moment a transcript commits.

        Disabling releases anything already waiting. Without that the switch appears not
        to work — the queued turn would sit there until max_wait expired, which looks like
        a stuck toggle rather than a bounded wait.
        """
        with self._lock:
            self.gate_on_turn = enabled
            release = (not enabled) and self._pending is not None
            if release:
                self._released = True
        print(f"[llm] floor gate {'on' if enabled else 'off'}")
        if release:
            self._try()

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
            gated = not self._released
            # Bound the wait: reply even if the turn model never emits a clean shift.
            # A self-contained timer means the gate doesn't depend on the VAP heartbeat.
            self._arm_locked(0.0 if self._released else self.max_wait)
        if gated and self.status is not None:
            self.status("waiting_for_turn", text)
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

    def _emit_clause(self, clause: str, first: bool = False) -> None:
        """Publish one speakable clause downstream (TTS + affect) as an ADD."""
        iu = self.create_iu(self._last_out)
        iu.payload = clause
        iu.text = clause
        # The model's own affect tag rides on the first clause, so AffectModule can set
        # the expression as speech begins rather than guessing from the text.
        iu.affect = self._affect if first else None
        self._last_out = iu
        self.append(retico_core.UpdateMessage.from_iu(iu, retico_core.UpdateType.ADD))

    def _commit_reply(self) -> None:
        """Mark end-of-utterance so TTS knows no more clauses are coming."""
        if self._last_out is None:
            return
        self.append(
            retico_core.UpdateMessage.from_iu(self._last_out, retico_core.UpdateType.COMMIT)
        )
        self._last_out = None

    def _stream_reply(self, messages: list[dict], user_text: str) -> str:  # noqa: D401
        """Stream the reply, emitting each clause as soon as it's complete.

        The reply may open with an affect tag (`[happy] ...`); it is stripped here so it
        never reaches TTS, and it arrives before the first clause, which is exactly when
        the face needs to be set.
        """
        buffer = ""
        spoken: list[str] = []
        looking_for_tag = True
        self._affect = None  # each turn gets its own reading
        for piece in chat_stream(
            self.base_url,
            self._model or "",
            messages,
            api_key=self._bearer(),
            extra_body=self.extra_body,
        ):
            buffer += piece
            if looking_for_tag:
                match = _AFFECT_TAG.match(buffer)
                if match:
                    self._affect = match.group(1).lower()
                    buffer = buffer[match.end() :]
                    looking_for_tag = False
                elif len(buffer) > 24 or "]" in buffer:
                    looking_for_tag = False  # no tag coming; don't keep scanning
                else:
                    continue  # wait for the tag to finish arriving
            # Flush every complete clause the buffer now contains.
            while True:
                cut = _split_point(buffer)
                if cut is None:
                    break
                clause = clean_reply(buffer[:cut])
                buffer = buffer[cut:]
                if clause:
                    self._emit_clause(clause, first=not spoken)
                    spoken.append(clause)
        tail = clean_reply(buffer)
        if tail:
            self._emit_clause(tail, first=not spoken)
            spoken.append(tail)
        return " ".join(spoken)

    def _reply(self, text: str) -> None:
        try:
            if self.status is not None:
                self.status("thinking", text)
            if self._model is None:
                self._model = resolve_model(self.base_url, self.configured_model, self._bearer())
            if not self._model:
                print(f"[llm] no model available at {self.base_url} (provider={self.provider_id})")
                return
            self._history.append({"role": "user", "content": text})
            system = self._system_prompt()
            messages = ([{"role": "system", "content": system}] if system else [])
            messages += self._history[-8:]
            reply = self._stream_reply(messages, text)
            if not reply:
                # Streaming produced nothing usable (small "thinking" models sometimes
                # do this). Fall back to one non-streamed attempt with a bigger budget.
                reply = chat(
                    self.base_url,
                    self._model,
                    messages,
                    max_tokens=512,
                    api_key=self._bearer(),
                    extra_body=self.extra_body,
                )
                if reply:
                    self._emit_clause(reply, first=True)
            print(f"[llm] user={text!r} -> {reply!r}")
            if not reply:
                # Never feed "" to TTS — and drop the dangling user message, otherwise
                # the next turn sees two user messages in a row and answers both at once.
                self._history.pop()
                print("[llm] empty reply after retry — turn dropped")
                return
            self._commit_reply()
            self._history.append({"role": "assistant", "content": reply})
            if self.status is not None:
                self.status("spoke", reply)
            # Stay muted for roughly as long as the reply takes to speak, so the agent
            # doesn't answer its own TTS bleeding back through the mic.
            # Just a debounce between turns. It used to add len(reply)/12 to keep from
            # talking over itself, but that is the speaking-state guard's job now, and
            # charging it here too muted the agent for 15 s after a normal reply (170 s
            # after a long one) — during which a second user turn was silently dropped,
            # because _enqueue overwrites _pending rather than queueing.
            self._muted_until = time.monotonic() + self.cooldown
        except Exception as exc:
            print(f"[llm] error: {exc}")
        finally:
            self._busy = False
            # A transcript may have queued up while we were replying — retry it (it will
            # respect the cooldown window we just set).
            self._try()
