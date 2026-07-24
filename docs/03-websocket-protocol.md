# 03 · WebSocket protocol

The bridge (`VizijWebSocketModule`) broadcasts newline-free JSON text frames on a single
WebSocket (default `ws://localhost:8765`). This document is the authoritative wire spec. It is
transport-versioned so the driver can reject mismatches.

## 3.1 Envelope

Every frame is one JSON object with a common envelope and a typed `payload`:

```jsonc
{
  "v": 1,                     // protocol version (integer, bumped on breaking change)
  "type": "turn.state",       // event type (namespaced, see §3.3)
  "ts": 1753142400.123,       // retico emit time, epoch seconds (float)
  "seq": 128,                 // monotonically increasing per-connection sequence number
  "iu": {                     // IU provenance (null for bridge-derived events)
    "id": "iu_9f3",
    "prev": "iu_9f2",         // predecessor IU id, or null
    "update": "ADD"           // "ADD" | "REVOKE" | "COMMIT"
  },
  "payload": { /* type-specific, see §3.3 */ }
}
```

Field notes:
- `v` — the driver refuses frames whose `v` it does not implement.
- `ts` — assigned at emit for latency measurement; the driver may add a receipt timestamp on its
  side (see [09](09-evaluation.md)). Not a scheduling clock.
- `seq` — lets the driver detect drops/reordering; strictly increasing per connection.
- `iu.update` — mirrors retico's update type. For events the bridge *derives* rather than forwards
  (e.g. `gaze.intent`), `iu` is `null` and the event is treated as a fresh ADD.

## 3.2 Update semantics on the wire

- **ADD** — a new hypothesis/impulse. The driver applies it (smoothed).
- **REVOKE** — retract a previously-added IU (same `iu.id` seen earlier as ADD). The driver
  cancels/reverses the visual impulse **iff** it has not fully played; otherwise ignores.
- **COMMIT** — finalize. Used to close utterances (`speech.end`) and to mark stable ASR; usually
  not itself expressive.

The driver keeps a short-lived map `iu.id → in-flight animation handle` so REVOKE can target the
exact tween. Handles are dropped when the tween completes or the utterance commits.

## 3.3 Event types

Seven types across the four capabilities plus speech. Each shows the payload schema and a concrete
example. The **target channel + verb/duration** for each lives in the editable mapping
(`web/src/drivers/reticoMapping.ts`, see [04](04-iu-animation-mapping.md)); it is summarized here
for readability but is *not* duplicated logic — the driver reads it from the config.

### 3.3.1 `turn.state` — turn-taking (retico-maai VAP)

```jsonc
{
  "v":1, "type":"turn.state", "ts":..., "seq":..,
  "iu":{"id":"iu_t12","prev":"iu_t11","update":"ADD"},
  "payload":{
    "state":"user_speaking",      // enum, see below
    "p_shift":0.18,               // [0,1] probability a turn shift is imminent
    "p_user":0.90                 // [0,1] probability the user holds the floor
  }
}
```
`state ∈ user_speaking | user_yielding | agent_should_speak | agent_speaking | mutual_silence`.
Emitted continuously at the VAP cadence; the driver de-dupes unchanged states and reacts to
transitions and to `p_shift` crossing thresholds.

### 3.3.2 `backchannel.cue` — backchannel prediction (retico-maai)

```jsonc
{
  "v":1, "type":"backchannel.cue", "ts":..., "seq":..,
  "iu":{"id":"iu_b7","prev":null,"update":"ADD"},
  "payload":{
    "kind":"continuer",           // "continuer" | "assessment" | "acknowledge"
    "intensity":0.6               // [0,1], scales amplitude of the visual response
  }
}
```
An **impulse**, not a state: a brief nod + brow flash (and optional mouth "mm"). No REVOKE in
practice (backchannels are momentary), but the driver tolerates one.

### 3.3.3 `nod.cue` — nod prediction (retico-maai)

```jsonc
{
  "v":1, "type":"nod.cue", "ts":..., "seq":..,
  "iu":{"id":"iu_n3","prev":null,"update":"ADD"},
  "payload":{
    "amplitude":0.7,              // [0,1] → maps to a max head-pitch angle
    "count":1                     // number of nod cycles
  }
}
```
Driver plays a scripted head-pitch oscillation (`count` cycles, ~0.18 s down-up each) scaled by
`amplitude`.

### 3.3.4 `speech.audio` / `speech.end` — agent speech + lip-sync (TTS)

```jsonc
{
  "v":1, "type":"speech.audio", "ts":..., "seq":..,
  "iu":{"id":"iu_s44","prev":null,"update":"ADD"},
  "payload":{
    "utteranceId":"u_44",
    "text":"Sure, I can help with that.",
    "format":"audio/wav;base64",  // or "audio/mpeg;base64"
    "data":"UklGR...",            // base64-encoded audio
    "sampleRate":22050
  }
}
```
```jsonc
{ "v":1, "type":"speech.end", "ts":..., "seq":..,
  "iu":{"id":"iu_s44e","prev":"iu_s44","update":"COMMIT"},
  "payload":{ "utteranceId":"u_44" } }
```
The driver hands `data` to the browser `AudioManager` (base64 → ArrayBuffer → decode → play) and
sets the current text; the reused `useVisemeMouth` derives viseme pose weights from the audio
(+text) client-side (Option A) or from Polly marks (Option B — then `data`/marks come from Polly).
`speech.end` zeroes residual visemes via `setInput`. Audio may be sent as one blob (MVP) or
chunked; chunked frames share `utteranceId` and add a `seqInUtterance` field.

### 3.3.5 `emotion.fer` — user emotion (FER, empathic mirror)

```jsonc
{
  "v":1, "type":"emotion.fer", "ts":..., "seq":..,
  "iu":{"id":"iu_f9","prev":"iu_f8","update":"ADD"},
  "payload":{
    "emotion":"happy",            // canonical label (see §3.4)
    "confidence":0.82,            // [0,1]
    "dist":{"happy":0.82,"sad":0.03,"surprise":0.05,"neutral":0.10}
  }
}
```
Drives the face to *mirror* the user: `poses/{emotion}.weight = confidence * 0.7`, slow tween
(0.5 s) with hysteresis (only re-animate on label change or Δconfidence > ~0.2) so FER noise does
not twitch the face.

### 3.3.6 `emotion.affect` — agent's own expression (LLM/TTS affect)

```jsonc
{
  "v":1, "type":"emotion.affect", "ts":..., "seq":..,
  "iu":{"id":"iu_a5","prev":null,"update":"ADD"},
  "payload":{
    "emotion":"concerned",
    "intensity":0.6,              // [0,1]
    "lengthSeconds":2.0           // hold before decaying to neutral
  }
}
```
Attack → hold → decay on the emotion pose weight (attack 0.25 s, decay over `lengthSeconds`).
Distinct from `emotion.fer`: this is what the *agent* feels/expresses, derived from the LLM's
affect tag or TTS prosody.

### 3.3.7 `gaze.intent` — gaze (bridge-derived)

```jsonc
{
  "v":1, "type":"gaze.intent", "ts":..., "seq":..,
  "iu":null,                       // derived by the bridge, not a forwarded IU
  "payload":{
    "mode":"mutual",              // "mutual" | "aversion" | "joint_attention" | "idle"
    "x":0.0, "y":0.0,             // normalized target (eye/head), [-1,1]
    "holdSeconds":1.5,            // auto-return after hold (for aversion)
    "durationSeconds":0.25        // tween duration
  }
}
```
The bridge derives gaze from turn state + LLM-pending ("thinking") + vision targets:
- `mutual` → eyes to camera (0,0) while listening.
- `aversion` → eyes up/left during turn planning, auto-return after `holdSeconds`.
- `joint_attention` → eyes (+head) to a referenced target `(x,y)`.
- `idle` → hand back to idle micro-saccade behavior.
Subject to the driver's gaze arbiter (§2.8).

## 3.4 Canonical enumerations

- **Emotion labels** (both `emotion.*` types map onto these; the driver uses
  `canonicalEmotionName` and the rig's `EMOTION_POSE_KEYS`):
  `neutral | happy | sad | angry | surprise | concerned | sleepy`.
  FER models with other label sets (e.g. FER+ "fear/disgust/contempt") are folded to the nearest
  canonical key in the bridge, not the driver.
- **Turn states** — see §3.3.1.
- **Backchannel kinds / gaze modes** — see the respective sections.

## 3.5 Client → server messages (control channel, optional)

The MVP is broadcast-only (server → clients). A minimal reverse channel is reserved for the demo
UI (not required for the vignettes):

```jsonc
{ "type":"control", "action":"set_vignette", "value":"listener" }   // scripting aid
{ "type":"control", "action":"mute_capability", "value":"fer" }     // toggle a stream
{ "type":"hello", "protocol":1, "faceId":"..." }                    // driver handshake
```
The server may ignore unknown control messages. The `hello` handshake lets the server confirm
protocol `v` compatibility before streaming.

## 3.6 Versioning & compatibility

- Bump `v` for any breaking change (renamed/removed field, changed enum meaning). Additive fields
  (new optional keys, new event types the driver can ignore) do **not** bump `v`.
- The driver logs and drops unknown `type`s rather than erroring — this lets the backend ship a
  new capability before the driver learns to render it.

## 3.7 Worked example — a fragment of "The Listener"

User says "so, um, I was thinking…"; timeline of frames (abridged):

```
seq  type              payload (abridged)
101  turn.state        state=user_speaking p_shift=0.05
102  gaze.intent       mode=mutual x=0 y=0            ← bridge: listen, look at user
103  backchannel.cue   kind=continuer intensity=0.4   ← "mm" + brow flash
110  turn.state        state=user_speaking p_shift=0.22
111  nod.cue           amplitude=0.6 count=1          ← nod at clause boundary
118  turn.state        state=user_yielding p_shift=0.71
119  gaze.intent       mode=mutual x=0 y=0 (hold)     ← hold gaze, anticipate turn
```
The face looks at the user, flashes a brow + "mm," nods once at the clause boundary, and holds
gaze as a turn hand-off becomes likely — all before the utterance is grammatically complete. That
"before it finishes" quality is the incrementality the paper foregrounds.
