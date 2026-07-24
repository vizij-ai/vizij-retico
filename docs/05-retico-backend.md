# 05 · retico backend (Python)

## 5.1 retico primer (the parts we rely on)

- **Incremental Unit (IU):** the atomic message. Has a `.payload`, a link to the IU it was
  grounded in / its predecessor, and travels inside an `UpdateMessage`.
- **UpdateMessage / UpdateType:** a batch of `(IU, update_type)` where `update_type ∈
  {ADD, REVOKE, COMMIT, UPDATE}`. Delivered to a module's `process_update_message`.
- **Modules:** `AbstractModule` and its kinds — `AbstractProducingModule` (e.g. microphone),
  `AbstractConsumingModule` (e.g. our bridge, a speaker), `AbstractTriggerModule`.
- **Buffers & wiring:** a module reads its **left buffer** (input) and writes its **right buffer**
  (output). `m1.subscribe(m2)` routes m1's right buffer into m2's left buffer.
- **Lifecycle:** `retico.network.run(head)` starts all reachable modules on their own threads;
  `retico.network.stop(head)` tears down.

## 5.2 The network

```
Microphone ─┬─▶ WhisperASR ──(committed text)──▶ LLM ──(reply+affect)──▶ TTS ─┐
            ├─▶ maai.TurnTaking (VAP) ───────────────────────────────────────┤
            ├─▶ maai.Backchannel ───────────────────────────────────────────┤
            └─▶ maai.NodPrediction ─────────────────────────────────────────┤
Webcam ─────▶ Vision ─▶ FER ────────────────────────────────────────────────┤
                                                                             ▼
                                                          VizijWebSocketModule (bridge)
```

Wiring sketch (`python/network.py`):

```python
mic   = MicrophoneModule()
asr   = WhisperASRModule()                 # incremental
vap   = TurnTakingModule(mode="vap_mc")    # retico-maai
bc    = BackchannelModule()                # retico-maai
nod   = NodPredictionModule()              # retico-maai
cam   = WebcamModule(); fer = FERModule()  # retico-vision (+ FER)
llm   = HFLMModule(...) # or an OpenAI/Gemini module
tts   = TTSModule(...)  # gTTS default / speechbrain offline
bridge = VizijWebSocketModule(host="0.0.0.0", port=8765)

mic.subscribe(asr); mic.subscribe(vap); mic.subscribe(bc); mic.subscribe(nod)
cam.subscribe(fer)
asr.subscribe(llm); llm.subscribe(tts)

for m in (vap, bc, nod, fer, llm, tts, asr):   # everything the bridge should forward
    m.subscribe(bridge)

retico.network.run(mic)      # also starts cam via reachability if wired to a head
```

The MaAI predictors subscribe to `mic` **in parallel** with `asr` — social signals must not wait
on transcription (see [02](02-architecture.md#22-the-retico-side)).

## 5.3 Module choices (default local/CPU, cloud swaps noted)

| Role | Default (no key, CPU) | Cloud swap (needs key) | Notes |
|---|---|---|---|
| ASR | `retico-whisperasr` (faster-whisper `small`, int8) | `retico-googleasr` | incremental; commit on stability |
| Turn-taking | `retico-maai` `TurnTakingModule` (VAP) | — | local only; the headline capability |
| Backchannel | `retico-maai` `BackchannelModule` | — | local |
| Nod | `retico-maai` `NodPredictionModule` | — | local |
| FER | `retico-vision` + small FER CNN (FER+/deepface) | Azure Face | webcam; label set folded to canonical |
| LLM | `retico-huggingfacelm` (Qwen2.5-1.5B / Llama-3.2-3B) | **OpenAI/Gemini (recommended for recorded demo)** | local CPU LLM is the latency bottleneck |
| TTS | `retico-googletts` (gTTS; net, no key) | — | offline fallback `retico-speechbraintts` |

Rationale: nothing in the default path needs a key; the one place a key clearly helps is the LLM
for the *recorded* demo (a multi-second local reply hurts the timing story). Turn-taking /
backchannel / nod are the differentiators and are all local.

## 5.4 `VizijWebSocketModule` design

A `AbstractConsumingModule` subclass that also hosts the WebSocket server.

Responsibilities:
1. **Server hosting.** Start a FastAPI app with a `websockets` endpoint on an asyncio loop in a
   background thread (retico runs its modules on their own threads; the socket I/O must not block
   `process_update_message`).
2. **IU classification.** Map each incoming IU to a protocol event type based on its source module
   / IU class (turn IU → `turn.state`, backchannel IU → `backchannel.cue`, audio IU from TTS →
   `speech.audio`, FER IU → `emotion.fer`, LLM affect → `emotion.affect`, …).
3. **Normalization.** Fold model-specific fields to the canonical schema ([03](03-websocket-protocol.md))
   — e.g. FER "fear/disgust" → nearest canonical emotion; VAP raw outputs → `state` + `p_shift`.
4. **Derivation.** Compute `gaze.intent` from turn state + an "LLM pending / thinking" flag +
   vision targets. This is bridge logic, not a forwarded IU (so `iu:null`).
5. **Framing.** Assign `seq`, `ts`, wrap in the envelope, `json.dumps`, broadcast to all clients.

Skeleton:

```python
class VizijWebSocketModule(retico_core.AbstractConsumingModule):
    @staticmethod
    def name(): return "Vizij WebSocket Module"

    def __init__(self, host="0.0.0.0", port=8765, **kw):
        super().__init__(**kw)
        self._clients = set()
        self._seq = 0
        self._utterance = 0
        self._loop = None          # asyncio loop in bg thread
        self._start_server(host, port)

    def process_update_message(self, update_message):
        for iu, ut in update_message:          # ut: ADD/REVOKE/COMMIT
            event = self._to_event(iu, ut)      # classify + normalize + derive
            if event is not None:
                self._broadcast(event)          # run_coroutine_threadsafe → send
        return None                              # consuming module returns nothing

    def _to_event(self, iu, ut): ...            # returns dict or None
    def _broadcast(self, event): ...            # thread-safe enqueue onto self._loop
```

Key correctness points:
- `process_update_message` returns quickly; the socket send is scheduled onto the asyncio loop via
  `asyncio.run_coroutine_threadsafe`, never awaited on retico's thread.
- `seq` is per-connection and monotonic; `ts` is stamped at event build for latency measurement.
- Utterance ids come from `self._utterance`; `speech.end` is emitted when the TTS audio IU
  commits (or when the module sees the utterance's final chunk).

## 5.5 Deriving `gaze.intent`

Pure function of recent state (kept minimal in the bridge):
- default `mode=mutual (0,0)` while `turn.state` is `user_speaking`/`user_yielding`.
- `mode=aversion` briefly when `agent_should_speak` fires and the LLM has not yet produced a reply
  ("thinking"), with an auto-return `holdSeconds`.
- `mode=joint_attention (x,y)` when vision indicates the user is attending to an off-camera target
  (future; MVP may stub this from a scripted cue in the Empathic Mirror vignette).
- `mode=idle` on `mutual_silence`.

## 5.6 Threading & shutdown

- retico modules: worker threads (framework-managed).
- WebSocket server: one asyncio loop on a dedicated thread; clients tracked in a set guarded for
  cross-thread access.
- On `retico.network.stop`, the module's `shutdown` closes client sockets and stops the loop.

## 5.7 What the bridge does *not* do

- No animation logic (that's the driver + mapping on the browser side).
- No viseme generation (client-side by default; Polly optional — see [06](06-vizij-frontend.md)).
- No persistence — it is a live relay. (A `--record` flag dumping the event stream to JSONL for
  offline replay/evaluation is a cheap, worthwhile addition; see [09](09-evaluation.md).)
