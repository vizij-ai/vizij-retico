#!/usr/bin/env bash
# Install the optional server-side FER path (retico-fer + EmoNet).
#
# LICENCE: EmoNet is CC BY-NC-ND 4.0 — non-commercial, no derivatives. This is for
# research use. The default browser FER path (MediaPipe, Apache-2.0) needs none of this.
#
#   ./scripts/install-emonet.sh      # from backend/
#
# Layout matters. retico-fer is not a package: its modules import each other flatly
# (`from fer_output_iu import ...`) and it resolves EmoNet's weights at
# <clone>/emonet/pretrained, so the emonet clone must sit *inside* the retico_fer clone,
# and the clone directory must be named with an underscore.
set -euo pipefail
cd "$(dirname "$0")/.."

VENDOR="vendor"
mkdir -p "$VENDOR"

if [ ! -d "$VENDOR/retico_fer" ]; then
  git clone --depth 1 https://github.com/retico-team/retico-fer.git "$VENDOR/retico_fer"
fi
if [ ! -d "$VENDOR/retico_fer/emonet" ]; then
  git clone --depth 1 https://github.com/face-analysis/emonet.git "$VENDOR/retico_fer/emonet"
fi
if [ ! -d "$VENDOR/retico-vision" ]; then
  git clone --depth 1 https://github.com/retico-team/retico-vision.git "$VENDOR/retico-vision"
fi

# dlib has no wheels for recent Pythons and builds from source (~3 min, needs a C++
# toolchain). opencv + retico-vision are ordinary installs.
# opencv-python-headless in a container: the GUI build pulls libGL/X11, which a server
# image has no use for and which makes `import cv2` fail with a missing libGL.so.1.
if [ "${VENDOR_ONLY:-0}" = "1" ]; then
  uv pip install "./$VENDOR/retico-vision" opencv-python-headless dlib
  # The project itself isn't installed at this point (Docker deps stage), so there is
  # nothing to verify against yet — the runtime stage does that.
  echo "vendored retico-fer + emonet + retico-vision"
  exit 0
fi

uv pip install "./$VENDOR/retico-vision" opencv-python dlib

uv run --extra full python -c "
from vizij_retico import emonet_fer
print('EmoNet FER available:', emonet_fer.available())
"
