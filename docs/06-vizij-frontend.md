# 06 · vizij frontend (browser)

See [`figures/03_visemes.d2`](figures/03_visemes.d2) for the viseme-path comparison.

## 6.1 App shell

- **Stack:** npm + Vite + React + Tailwind v4 + `@semio/ui` (Zustand only if local UI state
  outgrows React state).
- **Mount:** wrap the app in `VizijRuntimeProvider` with a `VizijAssetBundle` (the rigged GLB +
  rig/pose graph metadata) and render `VizijRuntimeFace`. The provider boots the runtime device
  and runs its tick loop (`autostart` / self-pacing).
- **State surface:** `useVizijRuntime()` for the control API (`setInput`/`animateValue`/
  `registerInputDriver`/`inputConstraints`); `useVizijOutputs(paths)` for live channel values;
  `useRigInput(path)` for one-off debugging controls.
- **Capture:** the frontend also owns mic/webcam via `getUserMedia` and streams them to the
  backend over the same WebSocket (`input.audio`/`input.video`); see §6.8.

> **Published-build note.** The npm `@vizij/runtime-react@0.2.0` we install is **orchestrator-wasm
> backed** (pre-Arora); the Arora `@vizij/runtime` device is repo `main` (0.3.0, unpublished). The
> public API (`VizijRuntimeProvider`/`VizijRuntimeFace`/`useVizijRuntime`/`setInput`/`animateValue`/
> `registerInputDriver`) is identical, so nothing above changes — bump to the Arora build when it
> publishes.

## 6.2 `VizijReticoDriver` — a `registerInputDriver` factory

The driver is registered once, at app start, and owns the WebSocket connection for its lifetime:

```ts
const lifecycle = useVizijRuntime().registerInputDriver("retico", (ctx) => {
  // ctx: { setInput, setRendererValue, namespace, faceId }
  let ws: WebSocket | null = null;
  const arbiter = createGazeArbiter();
  const inFlight = new Map<string, AnimHandle>();   // iu.id -> handle (for REVOKE)
  const channels = resolveChannels(ctx.faceId);     // semantic -> concrete paths, once

  return {
    start() {
      ws = connectWithBackoff(WS_URL, (msg) => dispatch(msg, ctx, channels, arbiter, inFlight));
    },
    stop()   { ws?.close(); ws = null; },
    dispose(){ arbiter.reset(); inFlight.clear(); },
  };
});
```

`dispatch` is the generic loop from [04 §4.6](04-iu-animation-mapping.md#46-how-the-driver-consumes-the-config-generic-loop):
look up the mapping entry for `msg.type`, apply hysteresis, run the named handler with resolved
targets + tuning + arbiter, and track/revoke by `iu.id`. The driver has **no** per-capability
branching beyond dispatching to a handler named in the config.

Why a driver and not ad-hoc `onmessage → setInput`: the provider owns lifecycle (mount/unmount,
error phase, driver count), so reconnects and teardown are clean, and multiple sources could
coexist. This mirrors how `apps/vizij-standalone`'s `useWebSocketSync` feeds `setInput` (its
transport is native/Tauri; ours is a browser socket).

## 6.3 Handlers (the only capability-specific code)

Small pure-ish functions, ported from existing reference logic:

- `gazePosture(event, ch, tuning, arbiter)` — turn-state → eye posture + brow; claims the `turn`
  gaze slot.
- `gazeTarget(event, ch, tuning, arbiter)` — `gaze.intent` → eye (+head) target; claims a slot per
  `mode` (`joint_attention`/`aversion`/`idle`). Reuse `useAgentFaceTools.applyGaze` math
  (L/R cross-eye offset via `mapNormalizedControlValue`).
- `impulseNodBrow(event, ch, tuning)` — backchannel impulse: brief head-pitch dip + brow flash
  (+ optional small `jaw.open`), scaled by `intensity`. Rides on top of gaze (uses `gaze.head`,
  does not take the gaze slot).
- `nodSequence(event, ch, tuning)` — `count` head-pitch cycles scaled by `amplitude`.
- `visemeSpeech(event, ch, tuning, audio)` — play audio via `AudioManager`; drive viseme pose
  weights with the reused `useVisemeMouth` (see §6.4).
- `emotionMirror(event, ch, tuning)` — FER → `poses/{emotion}.weight = confidence·cap`, slow
  tween + hysteresis.
- `emotionAffect(event, ch, tuning)` — agent affect → attack/hold/decay. Reuse
  `useAgentFaceTools.applyEmotion` (attack 0.25 s, decay = `lengthSeconds`, 0.7 cap).

All call `ctx.setInput` / `ctx.animateValue`. Reference files (GitHub `main`; local is stale):
`apps/tutorial-agent-face/src/hooks/useAgentFaceTools.ts`, `useVisemeMouth.ts`, `src/phoneme-core/`;
`packages/@vizij/runtime-react/src/utils/{posePaths,faceControls}.ts`.

## 6.4 Lip-sync — two viable paths

Both write the **same** viseme pose-weight channels (`rig/{faceId}/poses/{v}.weight`).

### Option A — client-side (recommended MVP default)
- Bridge sends `speech.audio` (audio bytes + text).
- Browser decodes/plays audio via `AudioManager`; the reused **`useVisemeMouth`** derives visemes
  from the browser's existing **`phoneme-core`** engine (`g2p_en` → phoneme timeline stretched to
  audio duration in `mode:"baseline"`; `mode:"align"` refines from audio features if CPU allows).
- **Pros:** no key; reuses ~500 lines of tested code; TTS choice becomes irrelevant to lip-sync;
  ~1 day to wire. **Cons:** baseline alignment is heuristic (align mode mitigates).

### Option B — AWS Polly (viable upgrade)
- Bridge (or browser) sends the reply **text** to AWS Polly, which returns audio + **viseme
  speech marks**; consume with `@vizij/speech-react.fetchVisemeData()` which maps Polly visemes to
  the pose channels (`pollyToLocalVisemes` in `phoneme-core`).
- **Pros:** higher-fidelity, engine-provided marks. **Cons:** needs an AWS Polly key/backend
  (cloud). Drop-in swap when available.

Decision: ship **A** for the MVP; keep **B** behind a config flag for a fidelity upgrade. The two
share the downstream viseme channels, so switching is localized.

## 6.5 Channel resolution & the head/nod unknown

At `start`, resolve semantic channel keys to concrete paths once (cache on the driver):
- emotion/viseme pose weights via `buildSemanticPoseWeightPathMap` → `rig/{faceId}/poses/{k}.weight`.
- eyes/eyelids/blink via `resolveFaceControls` (+ value mappers).
- **head/nod pitch is rig-specific.** It is discovered empirically at load time by logging the
  GLB's input-node metadata (`resolveFaceControls` + the bundle's `inputMetadata`), then stored
  under a `head.*` alias so the mapping never hard-codes a rig path. If absent, nod/backchannel
  head impulses degrade to brow-only with a console warning.

## 6.6 Idle & blink

When the gaze arbiter floor (`idle`) is active, run micro-saccades + periodic blink (reuse
`useIdleGazeBehavior`). Idle is suppressed while any higher-priority gaze intent holds and resumes
automatically. Blink is also triggered on turn hand-off (`agent_should_speak`).

## 6.7 Debug/demo UI (optional, `@semio/ui`)

A thin side panel (not required for the vignettes) to: show connection status + `seq`/latency;
toggle capability streams (`control.mute_capability`); pick the active vignette
(`control.set_vignette`); and display the live value of a few channels via `useVizijOutputs`.
Kept out of the driver so the driver stays a pure input source. (Step 1 ships a temporary
`devControls` panel that auto-generates a slider per `inputConstraints` entry.)

## 6.8 Capture & upstream (browser → backend)

The frontend captures the user and streams it to the backend over the same WebSocket:
- **Audio:** `getUserMedia({ audio })` → an **AudioWorklet** downsamples to PCM frames sent as
  `input.audio` (binary or base64). The backend `WebInputModule` wraps these as retico audio IUs.
- **Video:** `getUserMedia({ video })` → a low-rate (e.g. 5–10 fps) downscaled frame grab
  (`<canvas>` → JPEG) sent as `input.video`, wrapped as retico image IUs for FER.
- Secure context: fine on `http://localhost`; a LAN/remote host needs HTTPS.
- Kept in `frontend/src/capture/`, separate from the driver (which is output-only).

## 6.9 What the frontend does *not* do

- No dialogue logic (retico owns ASR/LLM/TTS/turn-taking); the browser only captures + streams.
- No networking beyond the one bidirectional WebSocket.
- No direct device calls — everything goes through `@vizij/runtime-react`
  (`setInput`/`animateValue`), so we ride the supported React surface and the device lifecycle the
  provider manages.
