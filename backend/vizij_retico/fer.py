"""Facial expression recognition — perceiving the *user*, switchable between two sources.

Until now the agent reacted only to speech timing; it could not see the person it was
talking to. This is the other half: the user's expression becomes an IU in the same graph,
so the face can mirror it.

Two providers, chosen at runtime (the same arrangement as ASR):

- **browser** — MediaPipe Face Landmarker runs in the page and streams 52 blendshape
  coefficients. Apache-2.0, no video ever leaves the browser, no server GPU/CPU cost.
  The blendshapes are turned into affect *here* rather than in the browser, so the
  perception→affect step stays a retico module and stays testable without a camera.
- **emonet** — `retico-fer` (EmoNet) over `retico-vision` ImageIUs, server-side. Predicts
  valence/arousal directly. NOTE: EmoNet is CC BY-NC-ND 4.0 — non-commercial, no
  derivatives — so it is fine for research but not for a commercial deployment. It is an
  optional extra and reports itself unavailable when not installed.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Optional

import retico_core
from retico_core.dialogue import GenericDictIU


class FerIU(GenericDictIU):
    """The *user's* observed expression.

    Distinct from AffectIU, which is what the agent itself feels. Keeping them separate
    matters: the face has to arbitrate between mirroring you and expressing itself.

    payload: {"emotion": str, "valence": float, "arousal": float,
              "confidence": float, "source": "browser"|"emonet"}
    """

    @staticmethod
    def type() -> str:
        return "Facial Expression Incremental Unit"


# --- blendshape -> affect ------------------------------------------------------------
# MediaPipe emits 52 ARKit-style coefficients in 0..1. This is a deliberately simple,
# legible mapping rather than a learned one: valence from smile-vs-frown, arousal from
# how "open" the face is, and a categorical label for the rig's emotion poses. It is a
# heuristic and is labelled as such in the event payload.
def _get(bs: dict[str, float], *names: str) -> float:
    """Mean of the named blendshapes that are present (handles left/right pairs)."""
    vals = [float(bs[n]) for n in names if n in bs]
    return sum(vals) / len(vals) if vals else 0.0


def affect_from_blendshapes(bs: dict[str, float]) -> dict[str, Any]:
    smile = _get(bs, "mouthSmileLeft", "mouthSmileRight")
    frown = _get(bs, "mouthFrownLeft", "mouthFrownRight")
    brow_down = _get(bs, "browDownLeft", "browDownRight")
    brow_up_outer = _get(bs, "browOuterUpLeft", "browOuterUpRight")
    brow_up_inner = _get(bs, "browInnerUp")
    jaw = _get(bs, "jawOpen")
    eye_wide = _get(bs, "eyeWideLeft", "eyeWideRight")
    squint = _get(bs, "eyeSquintLeft", "eyeSquintRight")

    valence = max(-1.0, min(1.0, smile - frown - 0.5 * brow_down))
    arousal = max(0.0, min(1.0, 0.5 * jaw + 0.5 * eye_wide + 0.3 * brow_up_outer))

    # Categorical label for the rig's emotion poses. Ordered by specificity: a face can
    # be smiling *and* wide-eyed, and "excited" is the better reading of that than either.
    if smile > 0.35 and eye_wide > 0.3:
        emotion = "excited"
    elif smile > 0.3:
        emotion = "happy"
    elif eye_wide > 0.4 or (jaw > 0.35 and brow_up_outer > 0.25):
        emotion = "surprise"
    elif brow_down > 0.35 and squint > 0.25:
        emotion = "anger"
    elif frown > 0.25 or brow_up_inner > 0.4:
        emotion = "sad"
    elif brow_down > 0.2:
        emotion = "concerned"
    else:
        emotion = "neutral"

    strength = max(smile, frown, brow_down, eye_wide, jaw, brow_up_inner)
    return {
        "emotion": emotion,
        "valence": round(valence, 3),
        "arousal": round(arousal, 3),
        "confidence": round(min(1.0, strength), 3),
    }


class BrowserFERModule(retico_core.AbstractProducingModule):
    """Blendshapes streamed from the browser -> FerIU."""

    @staticmethod
    def name() -> str:
        return "Browser FER Module"

    @staticmethod
    def description() -> str:
        return "Turns MediaPipe blendshapes from the browser into FerIUs."

    @staticmethod
    def output_iu():
        return FerIU

    def __init__(self, hub, min_change: float = 0.12, **kwargs) -> None:
        super().__init__(**kwargs)
        self.hub = hub
        # Expression is continuous and noisy; only emit when the reading actually moves,
        # otherwise the face twitches and the event log is unreadable.
        self.min_change = min_change
        self._last: Optional[dict[str, Any]] = None

    def process_update(self, _):
        try:
            item = self.hub.fer_in.get(timeout=1.0)
        except queue.Empty:
            return None
        blendshapes = item.get("blendshapes") or {}
        if not blendshapes:
            return None
        affect = affect_from_blendshapes(blendshapes)
        affect["source"] = "browser"
        if not self._changed(affect):
            return None
        self._last = affect
        iu = self.create_iu()
        iu.payload = affect
        return retico_core.UpdateMessage.from_iu(iu, retico_core.UpdateType.ADD)

    def _changed(self, affect: dict[str, Any]) -> bool:
        if self._last is None:
            return True
        if affect["emotion"] != self._last["emotion"]:
            return True
        return (
            abs(affect["valence"] - self._last["valence"]) > self.min_change
            or abs(affect["arousal"] - self._last["arousal"]) > self.min_change
        )


class FerGate(retico_core.AbstractModule):
    """Forwards FerIUs from the active source only (mirrors AsrGate)."""

    @staticmethod
    def name() -> str:
        return "FER Gate"

    @staticmethod
    def description() -> str:
        return "Forwards FerIUs from the active FER source only."

    @staticmethod
    def input_ius():
        return [FerIU]

    @staticmethod
    def output_iu():
        return FerIU

    def __init__(self, get_source: Callable[[], str], **kwargs) -> None:
        super().__init__(**kwargs)
        self.get_source = get_source

    def process_update(self, update_message):
        active = self.get_source()
        out = retico_core.UpdateMessage()
        forwarded = 0
        for iu, ut in update_message:
            if (getattr(iu, "payload", None) or {}).get("source") != active:
                continue
            out.add_iu(iu, ut)
            forwarded += 1
        return out if forwarded else None


class FerSwitcher:
    """Owns the active FER source and brings EmoNet up lazily (mirrors AsrSwitcher)."""

    def __init__(self, hub, gate: FerGate, on_status: Optional[Callable[[str, str], None]] = None):
        self.hub = hub
        self.gate = gate
        self.on_status = on_status
        self._emonet = None
        self._lock = threading.Lock()

    def set_source(self, source: str) -> None:
        source = "emonet" if source == "emonet" else "browser"
        if source == "emonet" and self._emonet is None:
            threading.Thread(target=self._start_emonet, daemon=True).start()
            self._notify("loading", "emonet")
            return
        self.hub.fer_source = source
        self._notify("active", source)

    def _start_emonet(self) -> None:
        with self._lock:
            if self._emonet is not None:
                return
            try:
                # Imported lazily: retico-fer/retico-vision are optional extras, and
                # EmoNet's weights are a manual install.
                from .emonet_fer import build_emonet_fer

                self._emonet = build_emonet_fer(self.hub, self.gate)
            except Exception as exc:
                print(f"[fer] EmoNet unavailable: {exc}")
                self._notify("error", str(exc))
                return
        self.hub.fer_source = "emonet"
        self._notify("active", "emonet")

    def _notify(self, state: str, detail: str) -> None:
        if self.on_status is not None:
            self.on_status(state, detail)
