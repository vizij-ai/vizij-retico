"""Affect: derive the agent's emotion from its own reply text.

A lightweight, keyword-based sentiment tag so the face expresses affect while it
speaks (a placeholder for a model-based affect signal). Emits `emotion.affect`
events that the frontend maps to the rig's emotion poses. The label set matches the
Quori rig's poses: happy | sad | anger | surprise | concerned | sleepy | neutral.
"""

from __future__ import annotations

from typing import Callable

from .events import EventFramer
from .hub import WebSocketHub

# Ordered by priority: the first matching emotion wins. Substrings, lower-cased.
_LEXICON: list[tuple[str, tuple[str, ...]]] = [
    ("surprise", ("wow", "whoa", "no way", "amazing", "incredible", "unbelievable", "really?", "guess what")),
    ("sad", ("sorry", "unfortunately", "sad", "regret", "afraid not", "miss you", "too bad")),
    ("anger", ("angry", "annoyed", "frustrat", "unacceptable", "furious")),
    ("concerned", ("careful", "worried", "concern", "not sure", "problem", "difficult", "hmm", "be cautious")),
    ("happy", ("glad", "great", "happy", "love", "wonderful", "awesome", "fun", "nice", "enjoy", "delighted", "haha", ":)")),
]


def infer_affect(text: str) -> tuple[str, float]:
    """Return (emotion, intensity in 0..1) for a reply. Neutral if nothing matches."""
    t = (text or "").lower()
    if not t.strip():
        return "neutral", 0.0
    for emotion, cues in _LEXICON:
        if any(cue in t for cue in cues):
            return emotion, 0.85
    # A trailing "!" without another cue reads as mild enthusiasm.
    if t.rstrip().endswith("!"):
        return "happy", 0.5
    return "neutral", 0.0


def make_emote_handler(hub: WebSocketHub, framer: EventFramer) -> Callable[[str], None]:
    """Return a handler that infers affect from `text` and broadcasts emotion.affect."""

    def emote(text: str) -> None:
        emotion, intensity = infer_affect(text)
        hub.broadcast(
            framer.frame("emotion.affect", {"emotion": emotion, "intensity": round(intensity, 3)})
        )

    return emote
