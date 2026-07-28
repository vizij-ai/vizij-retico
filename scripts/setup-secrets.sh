#!/usr/bin/env bash
# Create/update the project's secrets in Google Secret Manager, and let Cloud Run read
# them.
#
# Values are read from your environment — this script never prints them, and nothing is
# written to the repo. Set only the ones you want; anything unset is skipped, and the app
# will simply show that provider as unavailable rather than failing (the provider registry
# computes availability from the environment, so mounted secrets need no code change).
#
#   export AWS_ACCESS_KEY_ID=...         # Polly TTS (visemes)
#   export AWS_SECRET_ACCESS_KEY=...
#   export HF_TOKEN=...                  # optional: avoids HuggingFace rate limits
#   ./scripts/setup-secrets.sh
#
# Re-running is safe: an existing secret gets a new version rather than an error.
set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
if [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ]; then
  echo "error: no project. Pass PROJECT=... or run: gcloud config set project PROJECT" >&2
  exit 1
fi
echo "project: $PROJECT"

gcloud services enable secretmanager.googleapis.com --project "$PROJECT" >/dev/null

# secret-name : environment-variable
SECRETS=(
  "aws-access-key-id:AWS_ACCESS_KEY_ID"
  "aws-secret-access-key:AWS_SECRET_ACCESS_KEY"
  "hf-token:HF_TOKEN"
)

for entry in "${SECRETS[@]}"; do
  name="${entry%%:*}"
  var="${entry##*:}"
  value="${!var-}"

  if [ -z "$value" ]; then
    echo "  skip   $name  (\$$var not set)"
    continue
  fi

  if gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
    printf %s "$value" | gcloud secrets versions add "$name" \
      --project "$PROJECT" --data-file=- >/dev/null
    echo "  update $name  (new version)"
  else
    printf %s "$value" | gcloud secrets create "$name" \
      --project "$PROJECT" --replication-policy=automatic --data-file=- >/dev/null
    echo "  create $name"
  fi
done

# Accumulate as a space-separated string, not an array: macOS ships bash 3.2, where
# ${#arr[@]} on an empty array trips `set -u`, and "none configured" is a valid state.
#
# The IAM pass covers every secret that exists, not just the ones written above — so
# re-running with no env vars set still repairs a missing binding, which is exactly the
# situation you're in when a deploy fails with a permission error.
existing=""
for entry in "${SECRETS[@]}"; do
  name="${entry%%:*}"
  if gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
    existing="$existing $name"
  fi
done

if [ -z "${existing// /}" ]; then
  echo "nothing to do — no secret env vars were set, and no secrets exist yet."
  exit 0
fi

# Cloud Run reads secrets as its runtime service account, which needs accessor rights on
# each secret. Granting per-secret rather than project-wide keeps the blast radius small.
NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
SA="${RUNTIME_SA:-${NUMBER}-compute@developer.gserviceaccount.com}"
echo "granting secretAccessor to $SA"
for name in $existing; do
  gcloud secrets add-iam-policy-binding "$name" \
    --project "$PROJECT" \
    --member="serviceAccount:${SA}" \
    --role=roles/secretmanager.secretAccessor >/dev/null
  echo "  ok     $name"
done

echo
echo "done. Deploy with ./scripts/deploy.sh (it mounts whichever of these exist)."
