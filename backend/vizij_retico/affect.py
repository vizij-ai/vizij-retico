"""Affect: what the face expresses while the agent speaks.

Two sources, in order of preference:

1. The model declares it. The system prompt asks for a leading `[happy]`-style tag, so
   the affect is known *before the first clause is spoken* — which matters, because with
   streaming the face has to be set as speech starts, not after the reply is finished.
2. Keyword inference over the reply text, as a fallback for when the model ignores the
   instruction (small local models often do).

Emits `emotion.affect` events, which the frontend blends into the rig's emotion poses.
"""

from __future__ import annotations

from typing import Optional

import retico_core
from retico_core.text import GeneratedTextIU
from retico_core.dialogue import GenericDictIU

# Ordered by priority: the first matching emotion wins. Substrings, lower-cased.
_LEXICON: list[tuple[str, tuple[str, ...]]] = [
    ("surprise", ("wow", "whoa", "no way", "amazing", "incredible", "unbelievable", "really?", "guess what")),
    ("sad", ("sorry", "unfortunately", "sad", "regret", "afraid not", "miss you", "too bad")),
    ("anger", ("angry", "annoyed", "frustrat", "unacceptable", "furious")),
    ("concerned", ("careful", "worried", "concern", "not sure", "problem", "difficult", "hmm", "be cautious")),
    ("happy", ("glad", "great", "happy", "love", "wonderful", "awesome", "fun", "nice", "enjoy", "delighted", "haha", ":)")),
]


# Labels the model may declare. These must be keys the frontend's EMOTION_BLEND knows;
# blends like fear/excited/confused are expressed as mixtures of the rig's base poses.
AFFECT_LABELS = (
    "happy",
    "sad",
    "anger",
    "surprise",
    "concerned",
    "sleepy",
    "excited",
    "confused",
    "fear",
    "neutral",
)

AFFECT_INSTRUCTION = (
    " Begin every reply with an affect tag in square brackets showing how you feel, "
    "e.g. \"[happy] Good morning!\". Choose exactly one of: " + ", ".join(AFFECT_LABELS) + "."
)


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


def resolve_affect(text: str, declared: Optional[str] = None) -> tuple[str, float, str]:
    """(emotion, intensity, source) — the model's own tag if it gave one, else inferred."""
    label = (declared or "").strip().lower()
    if label in AFFECT_LABELS:
        return label, 0.85, "declared"
    emotion, intensity = infer_affect(text)
    return emotion, intensity, "inferred"


class AffectIU(GenericDictIU):
    """The agent's affective state.

    retico-core has no emotion IU, so — following the same convention retico-maai uses
    for VAPIU/BackchannelIU/NodIU — we define one over GenericDictIU.
    payload: {"emotion": str, "intensity": float, "source": "declared"|"inferred"}
    """

    @staticmethod
    def type() -> str:
        return "Affect Incremental Unit"


class AffectModule(retico_core.AbstractModule):
    """Reply text in, affect out.

    Keeping affect in the IU graph rather than broadcasting it from the LLM means it is
    a first-class signal: it can be revised (REVOKE/ADD) as better evidence arrives — a
    keyword guess now, the model's own tag a moment later, facial expression recognition
    of the *user* eventually — and anything downstream can subscribe to it, not just the
    WebSocket bridge.
    """

    @staticmethod
    def name() -> str:
        return "Affect Module"

    @staticmethod
    def description() -> str:
        return "Derives the agent's affective state from its reply."

    @staticmethod
    def input_ius():
        return [GeneratedTextIU]

    @staticmethod
    def output_iu():
        return AffectIU

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sent_for_utterance = False

    def process_update(self, update_message):
        out = retico_core.UpdateMessage()
        produced = False
        for iu, ut in update_message:
            if ut == retico_core.UpdateType.COMMIT:
                self._sent_for_utterance = False  # next utterance gets a fresh reading
                continue
            if ut != retico_core.UpdateType.ADD or self._sent_for_utterance:
                continue
            # First clause of an utterance: set the expression as speech begins.
            emotion, intensity, source = resolve_affect(
                getattr(iu, "text", "") or "", getattr(iu, "affect", None)
            )
            affect_iu = self.create_iu(iu)
            affect_iu.payload = {
                "emotion": emotion,
                "intensity": round(intensity, 3),
                "source": source,
            }
            out.add_iu(affect_iu, retico_core.UpdateType.ADD)
            self._sent_for_utterance = True
            produced = True
        return out if produced else None
