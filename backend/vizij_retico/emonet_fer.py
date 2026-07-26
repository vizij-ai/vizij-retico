"""Server-side FER via `retico-fer` (EmoNet) over `retico-vision`.

Kept in its own module and imported lazily, because none of this ships by default:

- `retico-vision` and `retico-fer` are git installs, not on PyPI.
- EmoNet's pretrained weights are a manual download.
- **EmoNet is CC BY-NC-ND 4.0** — non-commercial and no-derivatives. Fine for research
  and for the paper; not something to bake into a commercial deployment. The browser
  (MediaPipe, Apache-2.0) path exists precisely so there is a shippable option.

Install (research use):

    uv pip install git+https://github.com/retico-team/retico-vision.git
    uv pip install git+https://github.com/retico-team/retico-fer.git
    # plus EmoNet weights per that repo's README

The browser sends JPEG frames on `hub.video_in` (already plumbed), which this turns into
the ImageIUs retico-vision expects, so the camera still lives in the browser either way.
"""

from __future__ import annotations

import importlib.util
import io
import queue

import retico_core

from .fer import FerIU


def available() -> bool:
    """True if both retico-vision and retico-fer are importable."""
    return (
        importlib.util.find_spec("retico_vision") is not None
        and importlib.util.find_spec("retico_fer") is not None
    )


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
            payload = getattr(iu, "payload", None) or {}
            if not isinstance(payload, dict):
                continue
            fer = self.create_iu(iu)
            fer.payload = {
                "emotion": str(payload.get("emotion", "neutral")).lower(),
                "valence": round(float(payload.get("valence", 0.0)), 3),
                "arousal": round(float(payload.get("arousal", 0.0)), 3),
                "confidence": round(float(payload.get("confidence", 0.8)), 3),
                "source": "emonet",
            }
            out.add_iu(fer, retico_core.UpdateType.ADD)
            produced = True
        return out if produced else None


def build_emonet_fer(hub, gate):
    """Wire camera frames -> EmoNet -> FerIU -> gate, into the already-running network."""
    if not available():
        raise RuntimeError(
            "retico-vision / retico-fer not installed (optional, CC BY-NC-ND weights)"
        )
    from retico_fer import FERModule  # type: ignore

    images = WebImageModule(hub)
    emonet = FERModule()
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
