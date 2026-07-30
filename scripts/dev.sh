#!/usr/bin/env bash
# Run the backend locally against the same cloud services the deployment uses.
#
#   ./scripts/dev.sh            # lite  — no torch, fastest to start
#   ./scripts/dev.sh maai       # full  — adds VAP turn-taking + Whisper
#
# Then in a second terminal:
#   cd frontend && npm run dev        # http://localhost:5173
#
# The frontend talks to ws://localhost:8770/ws in dev (see FaceStage.tsx), so the two
# halves are independent — restart either without touching the other.
#
# Vertex, Cloud STT and Cloud TTS authenticate with your Application Default
# Credentials. If they report "no credentials", run:
#   gcloud auth application-default login
#
# Polly is the only thing needing a key; it is read from .env at the repo root (which is
# gitignored). Without it the UI simply shows Polly unavailable.
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-lite}"
PROJECT="${PROJECT:-vizij-retico}"

# Pin the project explicitly for every Google client. ADC otherwise resolves whatever
# `gcloud config` points at, which on this machine is a different project — that cost an
# afternoon once, with STT failing against a project nobody had mentioned.
export VERTEX_PROJECT="${VERTEX_PROJECT:-$PROJECT}"
export GOOGLE_ASR_PROJECT="${GOOGLE_ASR_PROJECT:-$PROJECT}"
export GOOGLE_TTS_PROJECT="${GOOGLE_TTS_PROJECT:-$PROJECT}"
export LLM_PROVIDER="${LLM_PROVIDER:-vertex}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

if [ -f .env ]; then
  set -a; . ./.env; set +a          # AWS keys for Polly; never printed
  echo "loaded .env"
fi

echo "mode=$MODE project=$PROJECT  →  ws://localhost:8770/ws"
cd backend
exec ./.venv/bin/python -u run.py "$MODE"
