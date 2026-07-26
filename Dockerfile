# vizij-retico — one image, two profiles.
#
#   PROFILE=lite (default)  browser ASR + OpenAI-compatible LLM + TTS. No torch, so the
#                           image is small and cold-starts fast. Good for a public demo.
#   PROFILE=full            adds retico-maai (VAP turn-taking/backchannel/nod) and local
#                           Whisper. Multi-GB and CPU-hungry; see docs/13 for the Cloud
#                           Run flags it needs (it is NOT viable with CPU throttling).
#
# Local (native arch — fine for testing, NOT deployable to Cloud Run from Apple Silicon):
#   docker build -t vizij-retico:lite .
#   docker run --rm -p 8080:8080 -e PORT=8080 vizij-retico:lite
#
# For Cloud Run you MUST produce linux/amd64 — Cloud Run does not run arm64 images, and
# a native build on Apple Silicon yields arm64 that fails at deploy:
#   docker buildx build --platform linux/amd64 -t IMAGE --push .
#   docker buildx build --platform linux/amd64 --build-arg PROFILE=full -t IMAGE --push .
# or let Google build it on amd64 hardware (avoids slow local emulation):
#   gcloud builds submit --tag IMAGE
#
# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- frontend ----
# The frontend builds against @vizij packages whose npm releases are broken, so the
# vizij-web monorepo is cloned and built at a pinned ref (override with --build-arg).
FROM node:22-slim AS web
ARG VIZIJ_WEB_REF=main
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN corepack enable

# Mirror the checkout layout the repo expects: the frontend's tsconfig resolves the
# @vizij types through `../../vizij-web-main`, so the worktree has to sit as a sibling of
# the repo root, not just wherever the vite alias points.
RUN git clone --depth 1 --branch ${VIZIJ_WEB_REF} \
      https://github.com/vizij-ai/vizij-web.git /work/vizij-web-main
WORKDIR /work/vizij-web-main
RUN pnpm install --frozen-lockfile && pnpm -r build

WORKDIR /work/vizij-retico/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
ENV VIZIJ_WEB_MAIN=/work/vizij-web-main
RUN npm run build

# -------------------------------------------------------------- python deps ---
# Built in a separate stage: retico-core depends on pyaudio, which compiles against
# portaudio, and none of that toolchain needs to ship in the final image.
FROM python:3.11-slim AS deps
ARG PROFILE=lite
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential portaudio19-dev git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock* ./
# Resolve dependencies before copying source so edits don't bust the layer cache.
RUN if [ "$PROFILE" = "full" ]; then \
      uv sync --extra full --no-install-project; \
    else \
      uv sync --no-install-project; \
    fi

# ----------------------------------------------------------------- backend ----
FROM python:3.11-slim AS runtime
ARG PROFILE=lite

# ffmpeg: pydub (the ASR resampler) shells out to it. libportaudio2: pyaudio's runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates ffmpeg libportaudio2 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
# Same path as the deps stage, so the venv's absolute paths stay valid.
COPY --from=deps /app/backend/.venv ./.venv
COPY backend/ ./

# Bake the frontend in and point the server at it: one container serves the SPA and
# the WebSocket on one port, which is what Cloud Run expects.
COPY --from=web /work/vizij-retico/frontend/dist /app/frontend-dist
# LLM_PROVIDER: LM Studio is a developer-machine convenience — inside a container
# localhost:1234 is the container itself. Deployments talk to Gemini, so supply
# GEMINI_API_KEY (Secret Manager). Override at deploy time if you tunnel to something else.
ENV VIZIJ_RETICO_STATIC=/app/frontend-dist \
    VIZIJ_RETICO_MODE=$PROFILE \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HF_HOME=/app/models \
    LLM_PROVIDER=gemini

# Pre-download the VAP and Whisper weights into the image. Cloud Run's filesystem is
# ephemeral, so without this every cold start re-downloads gigabytes from HuggingFace —
# slow, and it fails outright if egress is restricted. Best-effort: a download hiccup
# should not fail the build, it just costs a slower first request.
RUN if [ "$PROFILE" = "full" ]; then \
      .venv/bin/python -c "\
import os; os.environ.setdefault('HF_HOME','/app/models');\
print('pre-fetching VAP + Whisper weights…');\
import retico_maai, retico_whisperasr;\
from retico_maai import TurnTakingModule, BackchannelModule, NodPredictionModule;\
TurnTakingModule(mode='vap_mc', lang='en', frame_rate=10);\
BackchannelModule(lang='en', frame_rate=10);\
NodPredictionModule(lang='en', frame_rate=10);\
from retico_whisperasr import WhisperASRModule;\
WhisperASRModule(framerate=16000, language='en', silence_dur=1);\
print('weights cached')" || echo "WARN: weight pre-fetch failed; first request will download them"; \
    fi

EXPOSE 8080
# Run the venv directly rather than via `uv run`, which would try to re-resolve (and so
# would need git and the network) on every container start.
# Cloud Run sets $PORT; config.py binds 0.0.0.0 whenever it's present.
CMD ["sh", "-c", ".venv/bin/python -u run.py ${VIZIJ_RETICO_MODE}"]
