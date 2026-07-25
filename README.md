# vizij-retico

Connect the **retico** incremental spoken-dialogue framework (Python) to a **vizij-web**
real-time expressive face (React/TS over a Rust/WASM "Arora" runtime). A small Python bridge
streams retico's incremental dialogue signals — turn-taking, backchannels, nods, lip-sync,
emotion, gaze — over one WebSocket to the browser, where they drive the animated face in real time.

The system is the basis for a 4-page IEEE systems/demonstration paper for the
[IROS 2026 Human–Robot Dialogue workshop](https://human-robot-dialogue.github.io/).

> **Status: end-to-end loop working.** Speak → turn-taking → ASR → LLM → TTS → animated
> face, with runtime-switchable providers. See [Status](#status) for what is and isn't
> verified. Design docs are in [`docs/`](docs/README.md).

## Read the design

Start at **[`docs/README.md`](docs/README.md)** for the full document map. Highlights:

- [Architecture](docs/02-architecture.md) — data flow + the Arora device model
- [WebSocket protocol](docs/03-websocket-protocol.md) — the wire spec
- [IU → animation mapping](docs/04-iu-animation-mapping.md) — the editable behavior config
- [Capabilities](docs/07-capabilities.md) · [Vignettes](docs/08-demo-vignettes.md) ·
  [Evaluation](docs/09-evaluation.md) · [Build plan](docs/10-build-plan.md) ·
  [Paper outline](docs/11-paper-outline.md)
- Figures: [`docs/figures/`](docs/figures/)

## Layout

```
backend/    uv-managed retico backend: perception → dialogue → speech, over one WebSocket
frontend/   Vite/React app: VizijRuntimeProvider + VizijReticoDriver + reticoMapping.ts
docs/       design documentation
Dockerfile  one image, two profiles (lite | full) — see docs/13
```

## Run it

```bash
cd frontend && npm run dev
```

```bash
cd backend && uv run --extra full python run.py maai
```

Modes: `maai` (full perception), `lite` (browser ASR + LLM + TTS, no torch), `fake`
(synthetic events). Open http://localhost:5173, press **listen**, and talk. The `pipeline`
panel shows what's active at each stage; **dev** exposes the raw rig channels.

Containerized (SPA + WebSocket on one port): see
[docs/13](docs/13-containerization-and-cloud-run.md).

## Status

**Working, verified end to end:** turn-taking (retico-maai VAP) gating when the agent
speaks · ASR via browser Web Speech *or* local Whisper, switchable at runtime · streaming
LLM replies (LM Studio locally, Gemini in the cloud) that begin speaking before generation
finishes · gTTS speech · gaze, blinking, head nods, emotion blends, amplitude lip-sync ·
a provider selector that greys out anything missing its credentials.

**Written but not verified end to end:** AWS Polly viseme lip-sync (needs credentials);
the `full` container profile and any Cloud Run deployment.

**Known gaps:** no camera, so `emotion.fer` is never emitted and the agent's affect is
inferred from its own reply text by keyword rather than from the user · head motion is a
compositing-layer transform, because the rig's head transform isn't writable from this
runtime build ([docs/07 §7.8](docs/07-capabilities.md)) · the permissive CORS and
unauthenticated deployment make this a demo, not a service.
