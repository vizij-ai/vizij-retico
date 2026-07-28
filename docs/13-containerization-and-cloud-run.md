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
repo ships a [`cloudbuild.yaml`](../cloudbuild.yaml) for exactly this. Once per project:

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com
gcloud artifacts repositories create vizij --repository-format=docker --location=us-central1
```

Then build:

```bash
gcloud builds submit --config cloudbuild.yaml                              # lite
gcloud builds submit --config cloudbuild.yaml --substitutions=_PROFILE=full
```

**Wait a minute after enabling the APIs.** Submitting immediately fails with
`PERMISSION_DENIED: The caller does not have permission` even when your account is
project Owner — the Cloud Build service agent's IAM binding hasn't propagated yet. It
reads like a permissions problem you need to fix; it isn't. Retrying succeeds.

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

The shortest version: **a default deploy needs no secrets at all.** The LLM goes through
Vertex on the runtime service account's own credentials, and TTS falls back to gTTS. The
secrets below buy you the AI Studio LLM path and Polly visemes.

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
| `gemini-api-key` | `GEMINI_API_KEY` | the AI Studio LLM path | no — `deploy.sh` defaults to Vertex, which uses no key (below) |
| `aws-access-key-id` | `AWS_ACCESS_KEY_ID` | Polly visemes | no — falls back to gTTS + amplitude lip-sync |
| `aws-secret-access-key` | `AWS_SECRET_ACCESS_KEY` | Polly visemes | no |
| `hf-token` | `HF_TOKEN` | avoids HuggingFace rate limits on `full` | no |

Anything you don't set is skipped rather than erroring. That works because the provider
registry computes `available` from the environment, so an unmounted secret surfaces as a
greyed-out option in the UI instead of a runtime failure — the same mechanism that makes
[`providers.py`](../backend/vizij_retico/providers.py) honest locally.

### Minting the Gemini key without ever handling it

If you don't already have a key, `gcloud` can create one and hand it to Secret Manager
directly, so the value never appears on a terminal or in shell history:

```bash
gcloud services enable generativelanguage.googleapis.com apikeys.googleapis.com
gcloud services api-keys create --display-name="vizij-retico Gemini" \
  --api-target=service=generativelanguage.googleapis.com
KEY_UID=...   # the uid from `gcloud services api-keys list`
gcloud services api-keys get-key-string "$KEY_UID" --format='value(keyString)' \
  | tr -d '\n' \
  | gcloud secrets create gemini-api-key --replication-policy=automatic --data-file=-
```

`--api-target` restricts the key to the Gemini API, so a leak can't be spent on anything
else. **The `tr -d '\n'` is required**, not tidiness: `--format='value(...)'` appends a
newline, and a secret with a trailing newline produces a malformed `Authorization` header
that fails in a way pointing nowhere near the real cause. Verify with
`gcloud secrets versions access latest --secret=gemini-api-key | wc -c` — a Google API key
is exactly 39 bytes.

Note that `gcloud services api-keys list` returns **empty and exits 0** when
`apikeys.googleapis.com` is disabled, rather than erroring. An empty list is therefore not
evidence that a project has no keys until you've enabled that API.

### Or skip the key entirely: Gemini via Vertex AI

`deploy.sh` defaults to the **vertex** LLM provider, which needs no secret at all. Vertex
serves the same Gemini models over the same OpenAI-compatible protocol, but:

| | `gemini` (AI Studio) | `vertex` |
|---|---|---|
| Auth | static `GEMINI_API_KEY` | ADC — the runtime service account |
| Billing | AI Studio prepayment credits | the project's Cloud billing account |
| Secret to manage | yes | **none** |

That makes it the better default for a deployed demo: there is no key to mount, rotate or
leak, and spend lands on the same invoice as Cloud Run and Cloud Build. The runtime
service account needs `roles/aiplatform.user`:

```bash
gcloud projects add-iam-policy-binding PROJECT \
  --member="serviceAccount:PROJECTNUMBER-compute@developer.gserviceaccount.com" \
  --role=roles/aiplatform.user
```

Locally, `gcloud auth application-default login` supplies the same credentials. Two
things to know:

- **Tokens expire in about an hour**, so they are minted per request rather than captured
  when the provider is selected. A long-running instance would otherwise start returning
  401 mid-session, which reads as a permissions bug rather than an expiry.
- **Set `VERTEX_PROJECT` explicitly.** ADC resolves whatever project your local `gcloud
  config` points at, which is frequently not the one you are deploying to.
- **Gemini 2.5 thinks by default, and it is expensive here**: measured 575 reasoning
  tokens to produce a 20-token sentence, and with a small `max_tokens` the reply is
  truncated to nothing at all. The provider sets
  `thinking_config.thinking_budget = 0`. Note `reasoning_effort: "none"` is *rejected* by
  this endpoint — it accepts only `high`/`low`/`medium`/`minimal`.

### Gemini quota is separate from Cloud billing

A key can authenticate perfectly and still fail every generation call. Cloud Run and Cloud
Build bill through the project's Cloud billing account; the Gemini API bills through AI
Studio prepayment credits, which are **separate**. Symptom:

```
GET  /v1beta/openai/models            -> 200
POST /v1beta/openai/chat/completions  -> 429 RESOURCE_EXHAUSTED
     "Your prepayment credits are depleted."
```

A 429 rather than 401/403 is the tell that the key is fine and the quota is not. Top up at
[ai.studio/projects](https://ai.studio/projects) for the same project the key belongs to.

Two things the setup script does that are easy to miss by hand:

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
| `full` image builds end to end | ❌ not yet — but Cloud Build is now proven, so this is just a matter of running it |
| frontend builds with MediaPipe FER | ✅ production build clean |
| backend degrades without vendored EmoNet | ✅ registry reports unavailable, no crash |
| weights pre-fetch actually populates the image | ❌ untested (added, never run) |
| secret/deploy scripts emit the right `gcloud` calls | ✅ exercised against a stubbed `gcloud` |
| secrets reach `gcloud` via stdin, never argv | ✅ asserted by byte count in the stub |
| `lite` builds on Cloud Build (amd64) | ✅ 3m59s in project `vizij-retico` |
| `lite` deploys and serves on Cloud Run | ✅ `/health` 200 in 143 ms, SPA + 1.67 MB bundle |
| WebSocket `/ws` over TLS on Cloud Run | ✅ `hello` received with full registry |
| registry honest in a *deployed* container | ✅ whisper/emonet/gemini/polly all correctly unavailable |
| `GEMINI_API_KEY` mounts and authenticates | ✅ 200 from Gemini `/models`, `gemini-2.5-flash` listed |
| incremental ASR IUs stream over the cloud WebSocket | ✅ ADD-per-word then COMMIT, first frame 63 ms |
| gTTS synthesis in the cloud | ✅ 22 KB valid MP3 in 0.29 s via `control:say` |
| an actual LLM turn in the cloud | ✅ via Vertex — full turn in 1.17 s |
| the face renders in a deployed browser | ✅ WASM + rig load, no console errors |
| end-to-end from the deployed UI | ✅ heard → excited affect → speech → face animates |
| the AI Studio (`gemini`) path in the cloud | ❌ 429, prepayment credits — see below |

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
