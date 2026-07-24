# 10 · Build plan

Risk-ordered milestones (no fixed calendar). The guiding principle: **de-risk the bridge under
incremental churn first**, with the cheapest capability end-to-end, because everything else is
swappable and this is not.

## 10.1 Prerequisites (resolve before milestone 1)

- **Rigged `semio` GLB** — location/handoff of the face asset (in hand, per the plan).
- **`@vizij/*` package access** — how the browser app consumes `@vizij/runtime-react` /
  `@vizij/runtime` / `@vizij/render` on current `main` (published registry vs building from
  `vizij-web`/`vizij-rs`, which are locally stale). Pin `@vizij/runtime` **1.x**; watch PR #89.
- **Python env** — `retico-core` + `retico-maai` + `retico-whisperasr` (+ `retico-vision`/FER)
  installable on the target machine (portaudio present).
- **Decision:** cloud LLM key for the recorded demo? (available if wanted).

## 10.2 Milestones

1. **Scaffold + face renders.** npm + Vite + React + Tailwind + Base UI app; mount
   `VizijRuntimeProvider`/`VizijRuntimeFace` with the GLB. Log `resolveFaceControls` + input-node
   metadata to confirm gaze/pose/head channels (resolves the head/nod path unknown). Python venv +
   `retico-core`. **Gate:** manual `setInput` on a pose weight visibly moves the face.
2. **Bridge skeleton (riskiest, first).** `VizijWebSocketModule` (FastAPI + `websockets`) +
   `VizijReticoDriver` (`registerInputDriver` factory reading `reticoMapping.ts`). Wire only
   `WebInputModule → maai.TurnTaking → bridge → gaze`. Implement the envelope, `seq`/`ts`, REVOKE
   handling, and the gaze arbiter's `turn` slot. **Gate:** listening gaze tracks real speech,
   smoothly, median RTT < ~150 ms.
3. **Backchannel + nod.** Add `BackchannelModule` + `NodPredictionModule` → `backchannel.cue` /
   `nod.cue` → head/brow impulses that ride on top of gaze.
4. **Vignette 1 (Listener) demoable.** Tune impulse amplitudes/timings in the config.
5. **Speaking path.** `WhisperASR → LLM → TTS → speech.audio`+text; browser `AudioManager` + wire
   `useVisemeMouth` (Option A). Add `emotion.affect` from an LLM affect tag. **Gate:** avatar
   lip-syncs a reply with matched expression → **Vignette 2 (Speaker) demoable.**
6. **FER + gaze arbiter.** `retico-vision` + FER → `emotion.fer` (empathic mirror); `gaze.intent`
   `joint_attention`; finish arbiter priority. → **Vignette 3 (Empathic Mirror) demoable.**
7. **Integrate + tune.** All four together; tune durations/hysteresis/`leadMs`; idle/blink;
   confirm no channel conflicts.
8. **Robustness.** WS reconnect/backoff; REVOKE stress; graceful degradation (no webcam/key);
   bridge `--record` + replay + turn-based-baseline flag. Freeze vignette scripts.
9. **Record + measure.** Record the three vignettes (+ a baseline take of V1); produce the three
   evaluation figures and the architecture/mapping figures for the paper.

## 10.3 Critical path & parallelism

- **Critical path:** milestones 1 → 2 (the bridge + one capability) gate everything. Get a single
  signal flowing end-to-end before breadth.
- **Parallelizable once the bridge exists:** the Python module wiring (5) and the browser handlers
  (3, 6) are largely independent given the frozen protocol; the protocol + mapping are the
  contract between them, so pin those early (they are specified in [03](03-websocket-protocol.md) /
  [04](04-iu-animation-mapping.md)).

## 10.4 Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Bridge jitter under ADD/REVOKE churn | med | high | de-risk at milestone 2; `animateValue`-only + REVOKE cancel; hysteresis |
| End-to-end latency > 150 ms | med | high | same-machine/LAN; measure early; raise device tick rate |
| Head/nod channel not in rig | med | med | discover at milestone 1; degrade to brow-only |
| `@vizij/*` install/build friction (stale local) | med | med | confirm package access in prereqs; pin `main`/1.x |
| Local LLM too slow for a crisp hand-off | high | med | cloud LLM for the recorded demo |
| FER noise → twitchy mirror | med | low | hysteresis + slow tween |
| Client-side viseme sync loose | med | low | align mode; Polly (Option B) upgrade |
| PR #89 (device→runtime 2.0.0) lands mid-build | low | med | pin version; migrate deliberately if needed |

## 10.5 Definition of done (MVP)

- One running system; the three vignettes execute cleanly on it.
- All four capabilities visibly active and non-conflicting.
- The three evaluation figures produced from recorded runs.
- The mapping lives in `reticoMapping.ts` and is edited-not-coded to tune behavior.
- Figures + numbers handed to the paper author.
