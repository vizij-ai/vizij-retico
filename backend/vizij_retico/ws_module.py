"""VizijWebSocketModule — retico IUs → protocol events → browser.

A consuming module that fans in every subscribed producer's IUs, classifies each
into a protocol event (docs/03-websocket-protocol.md), and broadcasts it via the
shared hub. Classification is a registry keyed by IU class name so new capabilities
(turn-taking, backchannel, nod, FER, speech, affect) plug in without touching this
module's core loop.

A classifier is `fn(iu, update_type, framer) -> dict | None`.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import retico_core

from .events import EventFramer
from .hub import WebSocketHub

Classifier = Callable[[Any, retico_core.UpdateType, EventFramer], Optional[dict[str, Any]]]


class VizijWebSocketModule(retico_core.AbstractConsumingModule):
    @staticmethod
    def name() -> str:
        return "Vizij WebSocket Module"

    @staticmethod
    def description() -> str:
        return "Serializes incremental dialogue IUs into the Vizij WebSocket event protocol."

    @staticmethod
    def input_ius():
        return [retico_core.abstract.IncrementalUnit]

    def __init__(
        self,
        hub: WebSocketHub,
        classifiers: dict[str, Classifier],
        framer: Optional[EventFramer] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.hub = hub
        self.framer = framer or EventFramer()
        self.classifiers = classifiers

    def process_update(self, update_message):
        for iu, update_type in update_message:
            classify = self.classifiers.get(type(iu).__name__)
            if classify is None:
                continue
            event = classify(iu, update_type, self.framer)
            if event is not None:
                self.hub.broadcast(event)
        return None
