# vizij-retico

Connect the **retico** incremental spoken-dialogue framework (Python) to a **vizij-web**
real-time expressive face (React/TS over a Rust/WASM "Arora" runtime). A small Python bridge
streams retico's incremental dialogue signals — turn-taking, backchannels, nods, lip-sync,
emotion, gaze — over one WebSocket to the browser, where they drive the animated face in real time.

The system is the basis for a 4-page IEEE systems/demonstration paper for the
[IROS 2026 Human–Robot Dialogue workshop](https://human-robot-dialogue.github.io/).

## Live demo

**▶ [vizij-retico-86159759255.us-central1.run.app](https://vizij-retico-86159759255.us-central1.run.app)**

Press **listen**, allow the microphone, and talk (Chrome is the safest choice; the browser
ASR option needs Web Speech). Press **watch me** to
let the face read your expression from the camera (processed in the browser; the video
never leaves your machine).

There are two deployments, both rebuilt from `main` on every merge:

| | URL | What it runs |
|---|---|---|
| `lite` | [vizij-retico-86159759255…](https://vizij-retico-86159759255.us-central1.run.app) | Google STT or browser ASR · Gemini · Cloud TTS. Fast cold start. |
| `full` | [vizij-retico-full-86159759255…](https://vizij-retico-full-86159759255.us-central1.run.app) | adds retico-maai VAP turn-taking, backchannels, nods, local Whisper and EmoNet FER. The first connection cold-starts slowly. |

Both scale to zero, so the first visit after a quiet spell takes a few seconds (longer for
`full`). They are unauthenticated demo deployments — please don't hammer them.

> **Status: end-to-end loop working, locally and on Cloud Run.** Speak → turn-taking →
> ASR → LLM → TTS → animated face, with every provider switchable at runtime. See
> [Status](#status) for what is and isn't verified. Design docs are in
> [`docs/`](docs/README.md).

## Read the design

Start at **[`docs/README.md`](docs/README.md)** for the full document map. Highlights:

- [Architecture](docs/02-architecture.md) — data flow + the Arora device model
- [WebSocket protocol](docs/03-websocket-protocol.md) — the wire spec
- [IU → animation mapping](docs/04-iu-animation-mapping.md) — the editable behavior config
- [Capabilities](docs/07-capabilities.md) · [Vignettes](docs/08-demo-vignettes.md) ·
  [Evaluation](docs/09-evaluation.md) · [Build plan](docs/10-build-plan.md) ·
  [Paper outline](docs/11-paper-outline.md)
- [Containerization & Cloud Run](docs/13-containerization-and-cloud-run.md) ·
  [UI design](docs/14-ui-design.md)
- Figures: [`docs/figures/`](docs/figures/)

## Layout

```
backend/    uv-managed retico backend: perception → dialogue → speech, over one WebSocket
frontend/   Vite/React app: VizijRuntimeProvider + VizijReticoDriver + reticoMapping.ts
docs/       design documentation
scripts/    dev.sh (local backend), deploy.sh, setup-secrets.sh
Dockerfile  one image, two profiles (lite | full) — see docs/13
.github/    deploy.yml (both profiles on merge to main) · preview.yml (per-PR previews)
```

## Run it locally

Backend (first `cd backend && uv sync`, adding `--extra full` for the `maai` mode):

```bash
./scripts/dev.sh
```

Frontend, in a second terminal:

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 (the frontend talks to `ws://localhost:8770/ws` in dev).

`dev.sh` takes a mode: `lite` (default — Google STT / browser ASR, Gemini, Cloud TTS, no
torch), `maai` (adds VAP turn-taking, backchannels, nods and Whisper; needs
`uv sync --extra full`). `cd backend && uv run python run.py fake` runs a synthetic-event
graph with no cloud services at all.

The Google services (Vertex/Gemini, Cloud STT, Cloud TTS) use your Application Default
Credentials — run `gcloud auth application-default login` if they show as unavailable.
`dev.sh` pins them to the `vizij-retico` project (override with `PROJECT=…`). Polly is the
only provider needing a key; put `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in a
gitignored `.env` at the repo root. LM Studio works as a local LLM if one is running.

In the UI, **settings** picks providers, model and voice (anything missing credentials is
greyed out); **pipeline** shows what's active at each stage; **dev** exposes the raw rig
channels and debug controls.

Containerized (SPA + WebSocket on one port) and Cloud Run deployment: see
[docs/13](docs/13-containerization-and-cloud-run.md). Pull requests from this repo get
their own `lite` and `full` preview deployments, linked in a PR comment and deleted when
the PR closes.

## Status

**Working, verified end to end:** turn-taking (retico-maai VAP), with a runtime toggle to
reply immediately instead · barge-in that rejects the agent's own voice · ASR via Google
Cloud STT, browser Web Speech, or local Whisper, switchable at runtime · streaming LLM
replies (Gemini via Vertex AI, with a model picker and per-turn latency readout; or LM
Studio locally) that begin speaking before generation finishes · Google Cloud TTS (default),
gTTS or AWS Polly, with voice selection · Polly viseme lip-sync, amplitude lip-sync
otherwise · user facial-expression perception (browser MediaPipe, or EmoNet in `full`)
feeding empathic mirroring · gaze, blinking, head nods, emotion blends · both profiles
deployed on Cloud Run with CI deploys and per-PR previews.

**Not yet verified:** that the floor-gate toggle produces an *observable* behavioral
difference with a live user; `full`'s VAP throughput on Cloud Run CPU has not been
benchmarked (see [docs/13 §13.8](docs/13-containerization-and-cloud-run.md)).

**Known gaps:** head motion is a compositing-layer transform, because the rig's head
transform isn't writable from this runtime build
([docs/07 §7.8](docs/07-capabilities.md)) · the permissive CORS and unauthenticated
deployment make this a demo, not a service.
