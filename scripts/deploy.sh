#!/usr/bin/env bash
# Deploy to Cloud Run, mounting whichever secrets actually exist.
#
#   ./scripts/deploy.sh                 # lite  (browser ASR + Gemini + TTS)
#   PROFILE=full ./scripts/deploy.sh    # adds VAP turn-taking + local Whisper
#
# Secrets come from Secret Manager (see ./scripts/setup-secrets.sh) and are mounted as
# environment variables. The provider registry computes availability from the
# environment, so a secret you haven't set simply shows that provider as unavailable in
# the UI instead of failing at runtime — which is why this script mounts what exists
# rather than demanding a fixed set.
set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-vizij}"
PROFILE="${PROFILE:-lite}"
if [ "$PROFILE" = "lite" ]; then
  SERVICE="${SERVICE:-vizij-retico}"
else
  SERVICE="${SERVICE:-vizij-retico-$PROFILE}"
fi
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/vizij-retico:${PROFILE}"

if [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ]; then
  echo "error: no project. Pass PROJECT=... or run: gcloud config set project PROJECT" >&2
  exit 1
fi

# secret-name : ENV_VAR_TO_MOUNT_IT_AS
CANDIDATES=(
  "aws-access-key-id:AWS_ACCESS_KEY_ID"
  "aws-secret-access-key:AWS_SECRET_ACCESS_KEY"
  "hf-token:HF_TOKEN"
)

# Comma-separated string rather than an array: macOS ships bash 3.2, where ${#arr[@]} on
# an empty array trips `set -u` — and "no secrets configured" is a legitimate state here.
mounts=""
for entry in "${CANDIDATES[@]}"; do
  name="${entry%%:*}"
  var="${entry##*:}"
  if gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
    mounts="${mounts:+$mounts,}${var}=${name}:latest"
    echo "  mounting $var  <- $name"
  else
    echo "  skipping $var  (no secret '$name')"
  fi
done

args=(
  run deploy "$SERVICE"
  --project "$PROJECT" --region "$REGION"
  --image "$IMAGE"
  --port 8080
  --allow-unauthenticated
  # WebSocket connections are bounded by the request timeout; an hour is the maximum.
  --timeout 3600
  # The audio stream and the retico graph are per-instance state, so a client has to keep
  # talking to the instance holding its network.
  --session-affinity
  # Load-bearing, not cosmetic: polly.py calls boto3.client("polly") with no explicit
  # region, and a container has no ~/.aws/config to fall back on. Without this, Polly
  # fails with NoRegionError even when the credentials mount correctly.
  # Vertex by default: it bills to this project's ordinary Cloud billing account and
  # authenticates with the runtime service account's ADC, so the deployment needs no LLM
  # key at all. ASR likewise: Google STT authenticates with the same credentials.
  --set-env-vars "AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-us-east-1},LLM_PROVIDER=${LLM_PROVIDER:-vertex},VERTEX_PROJECT=${PROJECT},VERTEX_LOCATION=${VERTEX_LOCATION:-us-central1}"
)

if [ "$PROFILE" = "full" ]; then
  # --no-cpu-throttling is required, not optional: the retico network runs continuously
  # on background threads, and Cloud Run's default only allocates CPU while a request is
  # being handled, which stalls VAP inference between requests.
  #
  # --min-instances 0 is what keeps it free when idle, and it works here because of how
  # this app is shaped: the WebSocket *is* a long-running request, so an instance stays
  # alive with full CPU for as long as someone is connected, then scales to zero. Billing
  # is per instance-second, so nobody connected means no cost. The price is cold start —
  # the first connection waits for the container plus the VAP/Whisper weights, which is
  # why the Dockerfile bakes them in. Set MIN_INSTANCES=1 to trade money for that wait
  # before a live demo.
  args+=(--cpu 4 --memory 8Gi --no-cpu-throttling
         --min-instances "${MIN_INSTANCES:-0}")
fi

if [ -n "$mounts" ]; then
  args+=(--set-secrets "$mounts")
fi

echo
gcloud "${args[@]}"

echo
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format='value(status.url)'
