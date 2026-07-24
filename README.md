# vizij-retico

Connect the **retico** incremental spoken-dialogue framework (Python) to a **vizij-web**
real-time expressive face (React/TS over a Rust/WASM "Arora" runtime). A small Python bridge
streams retico's incremental dialogue signals — turn-taking, backchannels, nods, lip-sync,
emotion, gaze — over one WebSocket to the browser, where they drive the animated face in real time.

The system is the basis for a 4-page IEEE systems/demonstration paper for the
[IROS 2026 Human–Robot Dialogue workshop](https://human-robot-dialogue.github.io/).

> **Status: step 1 (project setup) in progress.** Frontend + backend scaffolds are in; see the
> Status section below. Design docs are in [`docs/`](docs/README.md).

## Read the design

Start at **[`docs/README.md`](docs/README.md)** for the full document map. Highlights:

- [Architecture](docs/02-architecture.md) — data flow + the Arora device model
- [WebSocket protocol](docs/03-websocket-protocol.md) — the wire spec
- [IU → animation mapping](docs/04-iu-animation-mapping.md) — the editable behavior config
- [Capabilities](docs/07-capabilities.md) · [Vignettes](docs/08-demo-vignettes.md) ·
  [Evaluation](docs/09-evaluation.md) · [Build plan](docs/10-build-plan.md) ·
  [Paper outline](docs/11-paper-outline.md)
- Figures: [`docs/figures/`](docs/figures/)

## Intended layout (not yet created)

```
backend/    uv-managed retico backend: WebInputModule + VizijWebSocketModule + network wiring
frontend/   Vite/React app: VizijRuntimeProvider + VizijReticoDriver + reticoMapping.ts + capture
docs/       design documentation
```

## Status (step 1, in progress)

- `frontend/` — Vite + React 19 + TS + Tailwind v4 + `@semio/ui`, consuming
  **`@vizij/runtime-react@0.1.0`** from public npm (the latest self-consistent set; `0.2.0` is
  broken on npm — see [docs/06](docs/06-vizij-frontend.md)). **Verified:** the Quori face GLB
  renders via `VizijRuntimeProvider`/`VizijRuntimeFace`, and a dev panel drives the 1356 resolved
  channels live via `setInput`. Rig exposes `/gaze/{left_right,up_down}`, `/lids/blink`, `/brow/*`,
  `/mouth/*`, `/poses/*` — but **no head-pitch channel**, so nods/backchannels use brow/eye/pose.
- `backend/` — uv (**Python 3.11**) + retico bridge on port **8770** (8765 is taken locally). A
  shared `WebSocketHub` runs `WebInputModule` (browser audio/video → IUs) and
  `VizijWebSocketModule` (IUs → JSON events). **Turn-taking verified end-to-end** with the real
  `retico-maai` VAP model (`retico-core`/`retico-maai` from git `main`; torch CPU): a speech WAV →
  `WebInputModule` → `TurnTakingModule` → bridge streams real `turn.state` events over the WS.
  Backchannel/nod classifiers are wired (live model test pending). A `fake` mode
  (`uv run run.py fake`) streams synthetic events with no torch.

Run: `cd frontend && npm run dev` · `cd backend && uv run run.py fake` (or `uv run run.py maai`).
