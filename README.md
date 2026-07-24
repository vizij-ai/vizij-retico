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

- `frontend/` — Vite + React 19 + TS + Tailwind v4 + `@semio/ui`, consuming `@vizij/runtime-react`
  from public npm. Face renders via `VizijRuntimeProvider`/`VizijRuntimeFace`; a dev panel drives
  channels via `setInput`. (Awaiting a rigged GLB at `frontend/public/assets/face.glb` to verify
  render.)
- `backend/` — uv + `retico-core` + FastAPI `/ws` echo on port **8770** (8765 is taken locally).
  Verified: `/health` + `/ws` round-trip.

Run: `cd frontend && npm run dev` · `cd backend && uv run run.py`.
