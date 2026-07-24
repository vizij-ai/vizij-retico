# 04 · IU → animation mapping

See [`figures/02_mapping.d2`](figures/02_mapping.d2) for the rendered mapping figure.

This mapping is the **intellectual core** of the system: the policy that turns discrete,
incremental, sometimes-revised dialogue signals into smooth, well-timed, non-conflicting facial
behavior. It is deliberately **data, not code** — it lives in one editable config file that the
driver interprets, so a capability can be added or retuned by editing a declarative entry rather
than driver logic.

## 4.1 Where it lives

`web/src/drivers/reticoMapping.ts` — a plain exported table keyed by protocol event `type`.
`VizijReticoDriver` ([06](06-vizij-frontend.md)) imports it and is otherwise generic: it receives
an event, looks up its entry, resolves channels, and applies the specified verb with the specified
timing, subject to the arbiter.

## 4.2 Design principles

1. **Smoothed by default.** Expressive changes use `animateValue` (a tween), never a hard
   `setInput` jump. `setInput` is reserved for resets (zeroing visemes, neutral-on-stop).
2. **Revisable.** Each application is tracked by `iu.id` so a REVOKE can cancel/reverse an
   in-flight tween. Fully-played impulses are not undone.
3. **Arbitrated.** Shared channels (gaze/head) obey a fixed priority; expressions (pose weights)
   compose but are capped.
4. **Rig-agnostic where possible.** Targets are expressed as *semantic* channel keys resolved to
   concrete paths at load time, so the same mapping works across rigs.
5. **Tunable in one place.** Durations, easings, amplitudes, thresholds, and priorities are all
   fields in the config, not magic numbers in the driver.

## 4.3 The config shape (proposed TypeScript)

```ts
// web/src/drivers/reticoMapping.ts
export type Verb = "animateValue" | "setInput" | "sequence";

export type ChannelKey =
  | "gaze.eyes" | "gaze.head"            // resolved via resolveFaceControls / head.*
  | "brow.raise" | "jaw.open"
  | `pose.emotion.${EmotionKey}`         // rig/{faceId}/poses/{emotion}.weight
  | `pose.viseme.${VisemeKey}`;          // rig/{faceId}/poses/{viseme}.weight

export interface Tuning {
  durationMs: number;                    // tween length
  easing?: "linear" | "easeIn" | "easeOut" | "easeInOut";
  poseCap?: number;                      // max weight (rig convention ≈ 0.7)
}

export interface MappingEntry {
  /** which channels this event may write */
  channels: ChannelKey[];
  verb: Verb;
  tuning: Tuning;
  /** arbitration priority when competing for a shared channel */
  priority?: "joint_attention" | "aversion" | "turn" | "idle";
  /** noise control for streaming inputs */
  hysteresis?: { minDelta?: number; minIntervalMs?: number };
  /** revoke behavior: can this impulse be reversed mid-flight? */
  revocable?: boolean;
  /** per-event handler hint the driver dispatches on (keeps driver generic) */
  handler:
    | "gazePosture" | "gazeTarget" | "impulseNodBrow" | "nodSequence"
    | "visemeSpeech" | "emotionMirror" | "emotionAffect";
}

export type ReticoMapping = Record<string /* event type */, MappingEntry>;
```

The `handler` field names a small set of pure functions in the driver (see §4.6); everything a
handler needs to *tune* comes from the entry, so editing the config changes behavior without
touching the handler.

## 4.4 The initial table (annotated)

| event `type` | channels | verb | tuning | handler | notes |
|---|---|---|---|---|---|
| `turn.state` | `gaze.eyes`, `brow.raise` | animateValue | 300–400 ms easeInOut | `gazePosture` | posture per `state`; `user_yielding`→brow raise ~0.2; blink on `agent_should_speak` |
| `backchannel.cue` | `gaze.head`, `brow.raise`, `jaw.open` | animateValue | 120–200 ms easeOut | `impulseNodBrow` | amplitude ← `intensity`; optional "mm" via small `jaw.open` |
| `nod.cue` | `gaze.head` | sequence | ~180 ms/cycle | `nodSequence` | `count` cycles, angle ← `amplitude` |
| `speech.audio` | `pose.viseme.*` | animateValue | 60 ms/frame (`leadMs` ~20) | `visemeSpeech` | drives `useVisemeMouth`; `speech.end`→`setInput` zero |
| `emotion.fer` | `pose.emotion.*` | animateValue | 500 ms easeInOut, cap 0.7 | `emotionMirror` | weight ← `confidence·0.7`; hysteresis minDelta 0.2 |
| `emotion.affect` | `pose.emotion.*` | animateValue | 250 ms attack / decay = `lengthSeconds` | `emotionAffect` | attack→hold→decay to neutral |
| `gaze.intent` | `gaze.eyes`, `gaze.head` | animateValue | 200–300 ms + hold | `gazeTarget` | `mode` sets target; priority per mode |

## 4.5 Gaze arbitration

Gaze is the most contended resource (turn posture, aversion, joint attention, and idle all want
the eyes). The driver keeps a single `activeGaze` slot chosen by fixed priority:

```
joint_attention  >  aversion  >  turn  >  idle
```

Rules:
- A higher-priority intent **preempts** a lower one and stores nothing to restore (postures are
  cheap to recompute).
- When the top intent clears (e.g. aversion's `holdSeconds` elapses, or joint-attention target
  leaves), the arbiter recomputes from remaining active intents and animates to the winner.
- `idle` is the floor: micro-saccades + blink resume whenever nothing else is active.
- Head and eyes can be split: `nod.cue`/`backchannel.cue` use `gaze.head` (pitch) as *impulses*
  that ride on top of the current eye posture without taking the gaze slot, so a nod during
  listening does not cancel mutual gaze.

Priorities and the impulse/posture split are all encoded in the config (`priority` field + which
`channels` an entry claims), so the arbitration policy is editable too.

## 4.6 How the driver consumes the config (generic loop)

```
onMessage(event):
  if event.v not supported: drop
  entry = mapping[event.type]; if !entry: log+drop
  targets = resolveChannels(entry.channels, faceId)   // semantic → concrete paths
  if entry.hysteresis and shouldSuppress(event): return
  handle = HANDLERS[entry.handler]
  applied = handle(event, targets, entry.tuning, arbiter)   // uses setInput/animateValue
  if event.iu?.update == "ADD" and entry.revocable:
     inFlight.set(event.iu.id, applied)                     // for later REVOKE
  if event.iu?.update == "REVOKE":
     inFlight.get(event.iu.id)?.cancelOrReverse()
```

The handlers are the only capability-specific code; they are small and pure (given targets +
tuning + arbiter), and they call `ctx.setInput` / `ctx.animateValue`. Reference logic to port:
`useAgentFaceTools` (gaze cross-eye offset, emotion attack/hold/decay, 0.7 cap) and
`useVisemeMouth` (viseme scheduling) — see [06](06-vizij-frontend.md).

## 4.7 Channel resolution (semantic → concrete)

At driver `start`, resolve semantic keys to concrete paths once and cache:
- `pose.emotion.{k}` / `pose.viseme.{k}` → `buildSemanticPoseWeightPathMap(...)` →
  `rig/{faceId}/poses/{k}.weight`.
- `gaze.eyes` → `resolveFaceControls(...)` eye position channels (+ `mapNormalizedControlValue`),
  handling the cross-eye split for L/R eyes.
- `gaze.head` → the rig's head-rotation/pitch channel — **rig-specific**; discovered from the
  GLB's input metadata at load time and stored under a `head.*` alias so the config need not hard-
  code it.
- `brow.raise`, `jaw.open` → resolved feature-space channels or specific pose keys per rig.

If a channel cannot be resolved (rig lacks it), the entry is disabled with a console warning and
the rest of the mapping still runs — capabilities degrade independently.

## 4.8 Extending the mapping (worked example)

To add an "eyebrow flash on user surprise" capability later, with no driver changes:

1. Backend: emit a new `emotion.fer` (already covered) or a new `reaction.cue` event.
2. Config: add an entry
   ```ts
   "reaction.cue": {
     channels: ["brow.raise"], verb: "animateValue",
     tuning: { durationMs: 150, easing: "easeOut" },
     handler: "impulseNodBrow", revocable: true,
   }
   ```
3. Done — the generic driver renders it. If the reaction needs new *behavior* (not just new
   tuning), add one small handler; otherwise reuse an existing one.

This is the property the user asked for: the mapping is a first-class, editable artifact.
