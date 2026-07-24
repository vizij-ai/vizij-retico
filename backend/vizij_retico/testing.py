"""Test doubles for exercising the bridge without the (heavy) MaAI models.

`FakeTurnModule` emits synthetic `turn.state` IUs on a timer so we can prove the
full path retico IU → VizijWebSocketModule → hub → browser end-to-end before the
real `retico-maai` predictors are wired in.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import retico_core

from .events import EventFramer, iu_provenance

_TURN_CYCLE = [
    {"state": "user_speaking", "p_shift": 0.05, "p_user": 0.95},
    {"state": "user_speaking", "p_shift": 0.20, "p_user": 0.90},
    {"state": "user_yielding", "p_shift": 0.70, "p_user": 0.55},
    {"state": "agent_should_speak", "p_shift": 0.85, "p_user": 0.20},
    {"state": "agent_speaking", "p_shift": 0.10, "p_user": 0.05},
    {"state": "mutual_silence", "p_shift": 0.30, "p_user": 0.50},
]


class TurnStateIU(retico_core.IncrementalUnit):
    @staticmethod
    def type() -> str:
        return "Turn State IU"


class FakeTurnModule(retico_core.AbstractProducingModule):
    """Cycles through turn states once per `period` seconds."""

    @staticmethod
    def name() -> str:
        return "Fake Turn Module"

    @staticmethod
    def description() -> str:
        return "Synthetic turn-state producer for bridge testing."

    @staticmethod
    def output_iu():
        return TurnStateIU

    def __init__(self, period: float = 0.8, **kwargs) -> None:
        super().__init__(**kwargs)
        self.period = period
        self._i = 0

    def process_update(self, _):
        time.sleep(self.period)
        payload = _TURN_CYCLE[self._i % len(_TURN_CYCLE)]
        self._i += 1
        iu = self.create_iu()
        iu.payload = dict(payload)
        return retico_core.UpdateMessage.from_iu(iu, retico_core.UpdateType.ADD)


def turn_state_classifier(
    iu: Any, update_type: retico_core.UpdateType, framer: EventFramer
) -> Optional[dict[str, Any]]:
    if update_type != retico_core.UpdateType.ADD:
        return None
    payload = dict(getattr(iu, "payload", None) or {})
    return framer.frame("turn.state", payload, iu=iu_provenance(iu, update_type))


# Classifier registry for the fake path (keyed by IU class name).
FAKE_CLASSIFIERS = {"TurnStateIU": turn_state_classifier}
