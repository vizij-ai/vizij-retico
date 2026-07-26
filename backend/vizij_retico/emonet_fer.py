"""Server-side FER via `retico-fer` (EmoNet) over `retico-vision`.

Kept in its own module and imported lazily, because none of this ships by default:

- `retico-vision` is a git install; `retico-fer` is not packaged at all and has to be
  vendored (its modules import each other flatly and it resolves weights by relative
  path). dlib builds from source, ~3 minutes.
- **EmoNet is CC BY-NC-ND 4.0** — non-commercial and no-derivatives. This project is
  research, so that is fine here; the browser (MediaPipe, Apache-2.0) path is what a
  commercial or publicly-hosted deployment would use.

Install:  ./scripts/install-emonet.sh   (~270 MB, gitignored)

Unlike the MediaPipe path, this one *does* upload the image: the browser sends JPEG
frames on `hub.video_in`, which this turns into the ImageIUs retico-vision expects. The
camera still lives in the browser, but the pixels leave it.
"""

from __future__ import annotations

import importlib.util
import io
import pathlib
import queue
import sys

import retico_core

from .fer import FerIU


#: Vendored clones. retico-fer is not a package — its modules import each other flatly
#: (`from fer_output_iu import ...`), and it resolves EmoNet's weights relative to its own
#: parent, so the emonet clone has to sit *inside* the retico_fer clone. Both directories
#: go on sys.path: the outer one for `emonet.models`, the inner for the flat imports.
_VENDOR = pathlib.Path(__file__).resolve().parents[1] / "vendor" / "retico_fer"
#: The emonet clone nests its package one level down (clone/emonet/), and fer_module
#: resolves weights at clone/emonet/pretrained — which this layout satisfies.
_PATHS = [_VENDOR / "emonet", _VENDOR / "retico_fer"]


def _ensure_path() -> None:
    for path in _PATHS:
        entry = str(path)
        if path.is_dir() and entry not in sys.path:
            sys.path.insert(0, entry)


def available() -> bool:
    """True if retico-vision and the vendored retico-fer/EmoNet are all present."""
    if importlib.util.find_spec("retico_vision") is None:
        return False
    _ensure_path()
    return (
        (_VENDOR / "retico_fer" / "fer_module.py").is_file()
        and (_VENDOR / "emonet" / "emonet" / "models").is_dir()
        and any((_VENDOR / "emonet" / "pretrained").glob("emonet_*.pth"))
        and importlib.util.find_spec("dlib") is not None
    )


#: EmoNet's labels -> the emotion vocabulary the face mapping understands.
EMONET_TO_AFFECT = {
    "neutral": "neutral",
    "happy": "happy",
    "sad": "sad",
    "surprise": "surprise",
    "fear": "fear",
    "disgust": "disgust",
    "anger": "anger",
    "contempt": "concerned",  # no contempt pose on this rig; concern is the closest read
}


class WebImageModule(retico_core.AbstractProducingModule):
    """Browser JPEG frames (hub.video_in) -> retico-vision ImageIU.

    The counterpart of WebInputModule for video: capture stays in the browser, so this
    is a producer rather than a webcam module.
    """

    @staticmethod
    def name() -> str:
        return "Web Image Module"

    @staticmethod
    def description() -> str:
        return "Emits ImageIUs from browser-streamed camera frames."

    @staticmethod
    def output_iu():
        from retico_vision.vision import ImageIU

        return ImageIU

    def __init__(self, hub, **kwargs) -> None:
        super().__init__(**kwargs)
        self.hub = hub

    def process_update(self, _):
        try:
            frame = self.hub.video_in.get(timeout=1.0)
        except queue.Empty:
            return None
        try:
            from PIL import Image

            image = Image.open(io.BytesIO(frame)).convert("RGB")
        except Exception as exc:
            print(f"[fer] could not decode camera frame: {exc}")
            return None
        iu = self.create_iu()
        # retico-vision's ImageIU carries a PIL image plus its dimensions.
        iu.set_image(image, 1, 1)
        return retico_core.UpdateMessage.from_iu(iu, retico_core.UpdateType.ADD)


class EmonetToFerIU(retico_core.AbstractModule):
    """Adapts retico-fer's output into this project's FerIU shape."""

    @staticmethod
    def name() -> str:
        return "EmoNet Adapter"

    @staticmethod
    def description() -> str:
        return "Normalizes retico-fer output into FerIU."

    @staticmethod
    def input_ius():
        return [retico_core.IncrementalUnit]

    @staticmethod
    def output_iu():
        return FerIU

    def process_update(self, update_message):
        out = retico_core.UpdateMessage()
        produced = False
        for iu, ut in update_message:
            if ut != retico_core.UpdateType.ADD:
                continue
            # FEROutputIU carries .emotion/.valence/.arousal as attributes, not a payload.
            label = str(getattr(iu, "emotion", "") or "neutral").strip().lower()
            try:
                valence = float(getattr(iu, "valence", 0.0) or 0.0)
                arousal = float(getattr(iu, "arousal", 0.0) or 0.0)
            except (TypeError, ValueError):
                valence = arousal = 0.0
            fer = self.create_iu(iu)
            fer.payload = {
                "emotion": EMONET_TO_AFFECT.get(label, label),
                "valence": round(valence, 3),
                # EmoNet's arousal is -1..1; the rig mapping wants 0..1 intensity.
                "arousal": round(abs(arousal), 3),
                "confidence": round(min(1.0, max(abs(valence), abs(arousal))), 3),
                "source": "emonet",
            }
            out.add_iu(fer, retico_core.UpdateType.ADD)
            produced = True
        return out if produced else None


def build_emonet_fer(hub, gate):
    """Wire camera frames -> EmoNet -> FerIU -> gate, into the already-running network."""
    if not available():
        raise RuntimeError(
            "EmoNet path unavailable — needs retico-vision, the vendored retico-fer + "
            "emonet clones, and dlib (see docs/14)"
        )
    _ensure_path()
    from fer_module import FERModule  # type: ignore[import-not-found]

    images = WebImageModule(hub)
    # 8-class model: the extra labels (disgust, anger, contempt) map onto poses
    # this rig actually has, so the richer set is worth the same compute.
    emonet = FERModule(emotions_class="extended")
    adapter = EmonetToFerIU()

    images.subscribe(emonet)
    emonet.subscribe(adapter)
    adapter.subscribe(gate)

    # retico's add_left_buffer() stops the target module, so anything already running that
    # we just subscribed into has to be restarted — the same trap as the ASR gate.
    gate.run(run_setup=False)
    for module in (images, emonet, adapter):
        module.run()
    return [images, emonet, adapter]
