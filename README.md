# vizij-retico

Connect the **retico** incremental spoken-dialogue framework (Python) to a **vizij-web**
real-time expressive face (React/TS over a Rust/WASM "Arora" runtime). A small Python bridge
streams retico's incremental dialogue signals — turn-taking, backchannels, nods, lip-sync,
emotion, gaze — over one WebSocket to the browser, where they drive the animated face in real time.

The system is the basis for a 4-page IEEE systems/demonstration paper for the
[IROS 2026 Human–Robot Dialogue workshop](https://human-robot-dialogue.github.io/).

> **Status: planning/design.** No system code yet — this repo currently holds design docs.

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
python/   VizijWebSocketModule + retico network wiring
web/       Vite/React app: VizijRuntimeProvider + VizijReticoDriver + reticoMapping.ts
docs/      design documentation (this is what exists today)
```
