# 02 · Architecture

See [`figures/01_architecture.d2`](figures/01_architecture.d2) for the rendered diagram.

## 2.1 End-to-end shape

```
Human ──speaks/appears──▶ [ retico network (Python) ] ──IU streams──▶ [ VizijWebSocketModule ]
                                                                              │ JSON over WS
                                                                              ▼
                                              [ Browser: VizijReticoDriver ] ──setInput/animateValue──▶
                                              [ Arora device store ] ──graph tick──▶ [ Vizij face ] ──▶ Human
```

Three tiers:

1. **retico network (Python).** Captures microphone + webcam, runs incremental ASR, the MaAI
   social predictors (turn-taking / backchannel / nod), FER, an LLM, and TTS. Everything is a
   module emitting IUs.
2. **The bridge (`VizijWebSocketModule`).** A single retico consuming module that also hosts a
   WebSocket server. It subscribes to every producing module, normalizes their IUs into one
   JSON protocol, and broadcasts to connected browsers. This is the only new server process.
3. **The browser face (React + Vizij).** A `registerInputDriver` factory (`VizijReticoDriver`)
   opens the WebSocket, interprets each event through the editable mapping, and writes values
   into the Arora device store; the behavior graph renders them on the face each tick.

## 2.2 The retico side

retico modules are wired with `m1.subscribe(m2)` (m1's right buffer → m2's left buffer) and run
with `retico.network.run(head)`. Two independent sensory chains feed the bridge:

**Audio chain** (from the microphone):
- `Microphone → WhisperASR` produces incremental word IUs (ADD/REVOKE as hypotheses firm up,
  COMMIT at stability). Committed text feeds the LLM.
- `Microphone → maai.TurnTaking` (VAP) produces turn-state IUs (probability of upcoming shift).
- `Microphone → maai.Backchannel` produces backchannel-cue IUs.
- `Microphone → maai.NodPrediction` produces nod-cue IUs.

  The MaAI predictors subscribe to **audio directly**, in parallel with ASR. This is deliberate:
  social signals must not wait on transcription — a nod or backchannel that arrives after the
  words is useless. This parallelism is the architectural reason the demo can feel responsive.

**Vision chain** (from the webcam):
- `Webcam → Vision → FER` produces user-emotion IUs, fully independent of the audio path.

**Generation chain** (agent output):
- Committed ASR text → `LLM` → reply text (+ an affect tag) → `TTS` → audio IU (+ the text).

All of these subscribe into the bridge. See [05](05-retico-backend.md) for module choices and the
`VizijWebSocketModule` design.

## 2.3 The bridge

The bridge is a `retico_core.abstract.AbstractConsumingModule` subclass that *also* owns a
FastAPI + `websockets` server (run on an asyncio loop in a background thread, since the retico
network runs on its own threads). Its `process_update_message(update_message)` is called by
retico whenever any subscribed module emits; for each `(IU, update_type)` pair it:

1. classifies the IU by source/type,
2. builds a protocol event (envelope + typed payload; see [03](03-websocket-protocol.md)),
3. enqueues it onto the asyncio loop for broadcast to all connected clients.

Design constraints:

- **Non-blocking.** `process_update_message` runs on retico's thread and must return fast;
  serialization is cheap and the actual socket send is handed to the asyncio loop via
  `run_coroutine_threadsafe`, never blocking the network.
- **Fan-in, single serialization point.** One module sees all streams, so ordering, sequence
  numbers, and timestamps are assigned in one place — essential for the driver's arbitration and
  for latency measurement.
- **Stateless-ish.** The bridge holds only what it needs to derive events (e.g. an utterance id
  counter, last turn-state for deriving `gaze.intent`). Heavy state lives in retico or the driver.

## 2.4 The Vizij side — the Arora device model

This is the part most worth understanding precisely, because it dictates how the browser consumes
the protocol. **Verified against vizij-web / vizij-rs `main`.**

Vizij now runs **as an Arora device**. Arora (crates.io `arora`) is a general device/runtime
framework; Vizij adapts onto it via `vizij-rs/crates/interop/*`, shipped to the browser as the
npm package **`@vizij/runtime`** (from `vizij-arora-web`). The model:

- **One device, one store.** The device owns a **blackboard store**: a map from string paths to
  typed values (`ValueJSON`, e.g. `{ float: 0.7 }`). This is the single ingestion point.
- **A behavior graph.** The device runs one composed graph as its "behavior." The graph's
  `input` nodes read specific store paths **each tick**; the graph computes rig deformations
  (morphs/bones/materials) and writes outputs back to the store.
- **Ticking.** Either the host calls `device.step(dtMs)` or the device self-paces with
  `device.run(periodMs)`. On `main`, animation runs entirely through the device (the old JS tick
  path was removed).

The raw device API (`@vizij/runtime`) is store-centric: `startDevice`, and on `AroraDevice`:
`setValue(path, value)`, `writeValues(values)`, `readValues`, `snapshot`, `drainChanges`,
`loadGraph`, `step`/`run`. **There is no `setInput`, `animateValue`, or `registerInputDriver` at
this layer — external input is just store writes.**

The React layer **`@vizij/runtime-react`** (`engine/aroraEngine.ts` owns the device lifecycle
behind `VizijRuntimeProvider`) adds the conveniences we actually target:

- `setInput(path, value, shape?)` → thin wrapper over `device.setValue`.
- `animateValue(path, target, { duration, easing })` → a tween that writes intermediate values
  over time; `cancelAnimation(path)` stops one.
- `registerInputDriver(id, factory)` → the idiomatic, lifecycle-managed extension point for an
  external real-time source. The factory receives `InputDriverContext = { setInput,
  setRendererValue, namespace, faceId }` and returns `{ start, stop, dispose }`. The provider
  tracks drivers and routes failures to an error phase.

**Consequence for us.** The browser consumer of our WebSocket is a `registerInputDriver` factory:
it opens the socket in `start`, and on each message calls `ctx.setInput` / `animateValue` on the
appropriate pose/gaze channel; it tears the socket down in `stop`/`dispose`. This is cleaner than
an ad-hoc `onmessage → setInput` because lifecycle (mount/unmount, reconnect, error) is owned by
the provider. The closest existing example is `apps/vizij-standalone`
(`hooks/useWebSocketSync.ts` + `aroraWsProtocol.ts`), which does inbound `setInput` and outbound
`subscribeToStoreChanges` — though its transport is native (Tauri/arora-sdk) rather than a browser
socket. (`apps/vizij-ws-app` is an **empty scaffold** on `main` — do not use it as a reference.)

**Version note.** `@vizij/runtime` is **1.x** on `main`; open PR #89 renames the API
"device"→"runtime" for a 2.0.0, with sibling renames `@vizij/animation-wasm → @vizij/animation`
and `@vizij/node-graph-wasm → @vizij/node-graph`. Pin to current `main` and expect the rename.

## 2.5 Channel paths

The face exposes canonical typed paths. Emotion and viseme blendshapes are pose weights:
`rig/{faceId}/poses/{key}.weight` (helper `buildSemanticPoseWeightPathMap`; key sets
`EMOTION_POSE_KEYS`, `VISEME_POSE_KEYS` in `utils/posePaths.ts`). Gaze/eyelids/blink resolve
through `resolveFaceControls` (`utils/faceControls.ts`), which returns the actual channel for the
rig (standard-vizij eye pos vs propsrig, etc.) plus value mappers (`mapNormalizedControlValue`,
`mapUnitControlValue`). **Head/nod channels are rig-specific** and are resolved empirically at
load time from the GLB's input metadata; the mapping abstracts nod behind a `head.*` entry. See
[04](04-iu-animation-mapping.md) and [06](06-vizij-frontend.md).

## 2.6 Timing and latency budget

Perceived responsiveness is the whole point, so latency is a first-class design concern.

- **Target:** median end-to-end (retico emit → value applied on the face) **< ~150 ms** for
  social signals (turn/backchannel/nod/gaze). Lip-sync is scheduled against audio playback and
  tolerates a fixed lead/offset rather than minimal latency.
- **Where time goes:** MaAI inference cadence (frames), bridge serialization (µs), WS transit
  (LAN/local, ms), driver dispatch + tween start (ms), device tick (bounded by `updateHz`).
- **Levers:** run the browser and retico on the same machine/LAN; keep the device tick rate high
  enough that a 0.15 s tween is smooth; keep MaAI on CPU but at a cadence that meets the budget;
  measure with per-event timestamps (see [09](09-evaluation.md)).

## 2.7 Handling incrementality (ADD / REVOKE / COMMIT) on the face

The face is continuous, but IUs are discrete and revisable. The driver's policy:

- **ADD** of a *social* signal → apply immediately as a smoothed impulse/posture via
  `animateValue` (never a hard `setInput` jump).
- **REVOKE** → if the corresponding visual impulse has not yet "committed" (e.g. a brow flash
  still mid-tween), cancel/reverse it; if it has already fully played, ignore (you cannot un-nod).
  This keeps ASR jitter from producing facial twitching.
- **COMMIT** → treat as final; e.g. `speech.end` commits an utterance and zeroes residual visemes
  via `setInput`.

`setInput` (immediate) is reserved for hard resets (zeroing visemes, forcing neutral on stop);
everything expressive uses `animateValue` so that revisable predictions render smoothly.

## 2.8 Shared-channel arbitration

Several capabilities compete for the same channels (especially the eyes/head). The driver runs a
small **arbiter** with fixed priority:

```
joint_attention  >  aversion (thinking)  >  turn-taking posture  >  idle
```

Only the highest-priority active intent controls gaze at any moment; lower ones are suppressed and
resume when it clears. Emotion (pose weights) and visemes (mouth poses) are largely orthogonal to
gaze and compose freely, but the arbiter also caps simultaneous pose-weight blends so expressions
don't sum past the rig's `0.7` convention. Details in [04](04-iu-animation-mapping.md).

## 2.9 Failure modes and degradation

- **No webcam** → FER/`gaze.intent(joint_attention)` disabled; the rest runs (Listener/Speaker
  vignettes unaffected).
- **No cloud LLM key** → fall back to a local HF model (higher latency; fine for non-recorded
  runs).
- **WS disconnect** → the driver retries with backoff; on reconnect it re-seeds neutral pose.
- **MaAI/model load failure** → the affected capability degrades to off; the bridge still forwards
  the others. No single capability is load-bearing for the others.

## 2.10 Why this architecture (alternatives considered)

- **retico-zmq → bridge → WS** instead of a custom module: viable for multi-process/multi-machine
  setups, but adds a hop and a dependency for no MVP benefit. Chosen: a single custom consuming
  module that hosts the WS directly.
- **Arora-native WS transport** (`arora-sdk`, as in `vizij-standalone`): real, but native/Rust
  side and Tauri-oriented; our producer is Python. Chosen: browser `registerInputDriver` over a
  plain WebSocket.
- **Generate visemes in Python:** requires phoneme timing (forced alignment or a viseme-emitting
  TTS) and a new IU type. Chosen: reuse the browser's existing client-side viseme engine; keep
  Polly as an optional higher-fidelity path. See [06](06-vizij-frontend.md) and
  [figures/03_visemes.d2](figures/03_visemes.d2).
