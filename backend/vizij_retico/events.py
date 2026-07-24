"""Protocol event framing (see docs/03-websocket-protocol.md).

Every outbound frame is `{ v, type, ts, seq, iu, payload }`. `EventFramer` owns
the monotonic `seq` counter and stamps `ts`; helpers build the `iu` provenance
block from a retico IncrementalUnit + UpdateType.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import retico_core

PROTOCOL_VERSION = 1


def iu_provenance(iu: Any, update_type: retico_core.UpdateType) -> dict[str, Any]:
    """Build the `iu` envelope block from a retico IU + update type."""
    prev = getattr(iu, "previous_iu", None)
    return {
        "id": str(getattr(iu, "iuid", None) or id(iu)),
        "prev": None if prev is None else str(getattr(prev, "iuid", None) or id(prev)),
        "update": update_type.name,  # ADD | REVOKE | COMMIT | UPDATE
    }


class EventFramer:
    def __init__(self) -> None:
        self._seq = 0

    def frame(
        self,
        type_: str,
        payload: dict[str, Any],
        iu: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        self._seq += 1
        return {
            "v": PROTOCOL_VERSION,
            "type": type_,
            "ts": time.time(),
            "seq": self._seq,
            "iu": iu,  # None for bridge-derived events (e.g. gaze.intent)
            "payload": payload,
        }
