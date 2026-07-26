# 13. Containerization and Cloud Run

One image, two profiles, because the two halves of this system have wildly different
resource shapes. Dialogue (ASR text in, LLM, TTS out) is I/O-bound and cheap. On-device
perception (VAP turn-taking, local Whisper) is a continuously-running torch workload.
Shipping them together would make a public demo expensive and slow to cold-start;
shipping only dialogue would drop the part the paper is actually about.

## 13.1 Profiles

| | `lite` (default) | `full` |
|---|---|---|
| ASR | browser (Web Speech) | browser **or** local Whisper |
| Turn-taking | none | retico-maai VAP + backchannel + nod |
| LLM / TTS | same in both (LM Studio / Gemini, gTTS / Polly) | same |
| torch | no | yes |
| Image | small | multi-GB |
| Cloud Run | comfortable | needs CPU always-on; measure before committing |

`lite` has no turn-taking model, so the LLM's floor gate has nothing to wait for and is
switched off — replies fire as soon as a transcript commits. That is a real behavioural
difference, not just a packaging one, and it is why `full` still matters for the paper.

## 13.2 Architecture: you cannot build this on Apple Silicon and deploy it

Two separate facts, both verified the hard way:

1. **Cloud Run runs `linux/amd64` only.** A native build on an M-series Mac produces
   `linux/arm64`, which Cloud Run rejects. (The `lite` image built during development was
   arm64 and would have failed at deploy.)
2. **The `full` profile cannot be built for arm64 at all.** `retico-maai` depends on
   `onnxruntime-gpu`, which publishes wheels only for `manylinux_2_27/2_28_x86_64` and
   `win_amd64`. On arm64 `uv sync --extra full` fails outright:
   *"Distribution onnxruntime-gpu==1.27.0 ... doesn't have a source distribution or wheel
   for the current platform."*

So the `full` image must be built on/for amd64 regardless. Build it on Cloud Build — the
repo ships a [`cloudbuild.yaml`](../cloudbuild.yaml) for exactly this:

```bash
gcloud artifacts repositories create vizij --repository-format=docker --location=us-central1
gcloud builds submit --config cloudbuild.yaml                              # lite
gcloud builds submit --config cloudbuild.yaml --substitutions=_PROFILE=full
```

It pins a bigger machine and disk (`E2_HIGHCPU_8`, 200 GB) and a 1 hour timeout, because
the frontend stage builds the whole vizij-web monorepo and `full` additionally installs
torch and pre-fetches model weights — the Cloud Build defaults are not enough for either.

Local cross-building works (`docker buildx build --platform linux/amd64`) but runs under
QEMU emulation: the dependency stage alone took ~75 s of downloads plus emulation
overhead and produced a **6.17 GB** layer before the app, weights or frontend.

Note that `onnxruntime-gpu` (210 MB) is pulled even though Cloud Run has no GPU. It falls
back to the CPU provider, so it works — it is just dead weight in the image. Pinning
`onnxruntime` instead would need an override upstream in retico-maai.

## 13.3 Build and run

```bash
# local testing only (native arch)
docker build -t vizij-retico:lite .
docker run --rm -p 8080:8080 -e PORT=8080 vizij-retico:lite

# deployable images — always amd64 (see 13.2)
docker buildx build --platform linux/amd64 -t IMAGE:lite --push .
docker buildx build --platform linux/amd64 --build-arg PROFILE=full -t IMAGE:full --push .
```

`docker build --build-arg PROFILE=full` on an arm64 host does not work — it fails in the
dependency stage, by design of the upstream wheels, not of this Dockerfile.

The frontend is baked in and served by the same FastAPI app, so one container serves the
SPA, the WebSocket (`/ws`) and the TTS routes (`/tts/*`) on one port. `PORT` is honoured
because Cloud Run injects it; when it is set the server also binds `0.0.0.0` instead of
loopback.

**The frontend build stage clones `vizij-ai/vizij-web` and builds it** — the published
`@vizij/*` npm releases are broken (see [12](12-local-vizij-main.md)), so there is no
shortcut here. Pin it for reproducible builds:

```bash
docker build -t vizij-retico:lite --build-arg VIZIJ_WEB_REF=<commit-sha> .
```

## 13.4 Secrets

Every credential lives in Secret Manager and is mounted as an environment variable at
run time. Nothing is baked into the image, and nothing is passed on a command line where
it would land in shell history or a process list.

Set whichever you have in your own shell, then run the setup script — it reads the values
from the environment, pipes them to `gcloud` over stdin, and never prints them:

```bash
export GEMINI_API_KEY=...            # LLM
export AWS_ACCESS_KEY_ID=...         # Polly TTS (visemes)
export AWS_SECRET_ACCESS_KEY=...
./scripts/setup-secrets.sh
```

| secret | env var | enables | required? |
|---|---|---|---|
| `gemini-api-key` | `GEMINI_API_KEY` | LLM replies | yes — the image defaults `LLM_PROVIDER=gemini` |
| `aws-access-key-id` | `AWS_ACCESS_KEY_ID` | Polly visemes | no — falls back to gTTS + amplitude lip-sync |
| `aws-secret-access-key` | `AWS_SECRET_ACCESS_KEY` | Polly visemes | no |
| `hf-token` | `HF_TOKEN` | avoids HuggingFace rate limits on `full` | no |

Anything you don't set is skipped rather than erroring. That works because the provider
registry computes `available` from the environment, so an unmounted secret surfaces as a
greyed-out option in the UI instead of a runtime failure — the same mechanism that makes
[`providers.py`](../backend/vizij_retico/providers.py) honest locally.

Two things the script does that are easy to miss by hand:

- **Grants `roles/secretmanager.secretAccessor`** to the Cloud Run runtime service
  account (`PROJECTNUMBER-compute@…` by default; override with `RUNTIME_SA=`). Cloud Run
  reads secrets *as that account*, and without the binding the deploy succeeds and the
  container then fails to start. Grants are per-secret, not project-wide.
- **Re-runs are safe and repair IAM.** An existing secret gets a new version rather than
  an error, and the IAM pass covers every secret that exists — so re-running with nothing
  exported still fixes a missing binding, which is the state you're in when a deploy dies
  with a permission error.

## 13.5 Deploying to Cloud Run

```bash
./scripts/deploy.sh                  # lite
PROFILE=full ./scripts/deploy.sh     # full
```

It checks which secrets exist and mounts only those, so the same command works whether or
not you configured Polly, and applies the `full`-only resource flags described below.
`PROJECT`, `REGION`, `REPO` and `SERVICE` are all overridable by environment variable.

Equivalent by hand, for the record:

```bash
gcloud run deploy vizij-retico \
  --image us-central1-docker.pkg.dev/PROJECT/vizij/vizij-retico:lite \
  --region us-central1 --allow-unauthenticated --port 8080 \
  --timeout 3600 --session-affinity \
  --set-env-vars AWS_DEFAULT_REGION=us-east-1 \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest,\
AWS_ACCESS_KEY_ID=aws-access-key-id:latest,\
AWS_SECRET_ACCESS_KEY=aws-secret-access-key:latest
```

`full` additionally needs `--cpu 4 --memory 8Gi --no-cpu-throttling --min-instances 1`.

`AWS_DEFAULT_REGION` is load-bearing rather than cosmetic: `polly.py` calls
`boto3.client("polly")` with no explicit region, and a container has no `~/.aws/config` to
fall back on, so Polly fails with `NoRegionError` even when the credentials mount fine.

Things that will bite otherwise:

- **WebSockets** work on Cloud Run but the connection is bounded by the request timeout;
  `--timeout 3600` gives the maximum hour. The client already reconnects with backoff.
- **CPU throttling.** By default Cloud Run only allocates CPU while a request is being
  handled. The retico network runs continuously on background threads, so `full` needs
  `--no-cpu-throttling` and realistically `--min-instances=1`; otherwise VAP inference
  stalls between requests. This is the main reason `full` costs real money.
- **Session affinity** (`--session-affinity`) if you scale past one instance: the audio
  stream and the retico graph are per-instance state, so a client must keep talking to
  the instance that holds its network.
- **LM Studio does not exist in the cloud.** The default LLM provider points at
  `localhost:1234`, which in a container is the container. Set `LLM_PROVIDER=gemini` and
  supply `GEMINI_API_KEY`, or the first turn fails with "no model available".
- **Cold start** on `full` is dominated by model loading. The Dockerfile now pre-fetches
  the VAP and Whisper weights into `HF_HOME=/app/models` at build time, because Cloud
  Run's filesystem is ephemeral and without it *every* cold start re-downloads gigabytes.
  The pre-fetch is best-effort: a download hiccup logs a warning rather than failing the
  build, so check the build log if first-request latency looks wrong.
- **Startup probe** is not a problem by construction: `hub.start()` binds the port before
  the heavy modules are built, so Cloud Run sees a listening socket within seconds even
  while VAP is still loading. Requests arriving in that window get the SPA and `/health`;
  the retico graph simply is not producing events yet.
- **Memory.** `full` loads torch, VAP and Whisper — budget several GiB
  (`--memory 8Gi` is a sane starting point) and measure.

## 13.6 FER in a deployed image

Both FER providers exist, but only one is deployed, and that is deliberate:

- **browser (MediaPipe, Apache-2.0)** — runs in the page, needs nothing server-side, and
  only blendshape coefficients cross the wire. This is what a deployed image uses, and it
  costs the container nothing.
- **emonet (CC BY-NC-ND)** — vendored under `backend/vendor/`, which
  [`.gcloudignore`](../.gcloudignore) excludes from the upload. Three reasons: ~270 MB of
  weights, per-frame dlib + EmoNet inference on Cloud Run CPU (with JPEG frames uploaded
  from the browser, so it is slower *and* less private), and publishing non-commercial
  weights inside a public container image is a distribution question worth avoiding.

Nothing breaks in its absence — verified: `available()` returns False, the registry still
builds and simply shows emonet as unavailable, and attempting to select it raises a clear
error rather than failing obscurely. EmoNet stays a local research option, installed with
`backend/scripts/install-emonet.sh`.

## 13.7 What is actually verified

| | status |
|---|---|
| `lite` image builds | ✅ 630 MB (arm64, locally) |
| `lite` serves SPA + `/health` + WebSocket | ✅ verified in a running container |
| `lite` genuinely omits torch | ✅ verified inside the image |
| provider registry reports honestly in-container | ✅ whisper shows unavailable in `lite` |
| `full` dependencies resolve and install (amd64) | ✅ 104 packages, torch 2.13.0 — 6.17 GB deps layer |
| `full` image builds end to end | ❌ not yet — needs an amd64 builder |
| frontend builds with MediaPipe FER | ✅ production build clean |
| backend degrades without vendored EmoNet | ✅ registry reports unavailable, no crash |
| weights pre-fetch actually populates the image | ❌ untested (added, never run) |
| secret/deploy scripts emit the right `gcloud` calls | ✅ exercised against a stubbed `gcloud` |
| secrets reach `gcloud` via stdin, never argv | ✅ asserted by byte count in the stub |
| the scripts against a real GCP project | ❌ never run — needs your project |
| anything on Cloud Run | ❌ never deployed |

## 13.8 Honest limits

- `--allow-unauthenticated` plus the permissive CORS in the hub makes this a **demo**
  deployment, not a hardened service. Anyone with the URL can drive the face and spend
  your Gemini/Polly quota. Put it behind IAP or an auth proxy for anything public.
- Audio is streamed to the backend for turn-taking in `full`; over the public internet
  that is bandwidth and latency you do not have locally. Measure before claiming
  real-time behaviour in a deployed setting.
- `full` on Cloud Run CPU has not been benchmarked. If VAP can't keep up at 10 Hz, the
  outs are a GPU-backed revision or splitting perception onto another host with
  `retico-zmq`.
