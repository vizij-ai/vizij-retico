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

## 13.2 Build and run

```bash
docker build -t vizij-retico:lite .
docker build -t vizij-retico:full --build-arg PROFILE=full .
docker run --rm -p 8080:8080 -e PORT=8080 vizij-retico:lite
```

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

## 13.3 Deploying to Cloud Run

```bash
gcloud run deploy vizij-retico \
  --image gcr.io/PROJECT/vizij-retico:lite \
  --allow-unauthenticated --port 8080 --timeout 3600 \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest
```

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
- **Secrets** (`GEMINI_API_KEY`, `AWS_*`) belong in Secret Manager, mounted as env vars.
  The provider registry computes availability from the environment, so a missing secret
  shows up as a greyed-out option in the UI rather than a runtime failure.
- **Cold start** on `full` is dominated by model loading. The image bakes in the Python
  deps, but HF/VAP weights still download on first use unless you pre-warm them into the
  image — worth doing before any demo.

## 13.4 Honest limits

- `--allow-unauthenticated` plus the permissive CORS in the hub makes this a **demo**
  deployment, not a hardened service. Anyone with the URL can drive the face and spend
  your Gemini/Polly quota. Put it behind IAP or an auth proxy for anything public.
- Audio is streamed to the backend for turn-taking in `full`; over the public internet
  that is bandwidth and latency you do not have locally. Measure before claiming
  real-time behaviour in a deployed setting.
- `full` on Cloud Run CPU has not been benchmarked. If VAP can't keep up at 10 Hz, the
  outs are a GPU-backed revision or splitting perception onto another host with
  `retico-zmq`.
