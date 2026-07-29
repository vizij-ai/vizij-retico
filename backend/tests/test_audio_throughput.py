"""Does streamed audio actually keep up with real time?

This is the test that was missing. The previous ASR verification called
`GoogleASRModule.process_update()` directly, which bypasses retico's module loop — and the
module loop was the bug. A consuming `AbstractModule` takes one UpdateMessage per left
buffer per iteration and sleeps 20 ms between iterations, so it accepts ~50 messages/s no
matter how fast the producer runs. With one 10 ms frame per message that is 0.5 s of audio
per second of wall clock, and the backlog grows forever.

So: push audio in at real time through a *running* WebInputModule and assert the consumer
keeps up. Anything that reintroduces per-frame messages fails here.

    ./.venv/bin/python -m pytest tests/test_audio_throughput.py -v
"""

from __future__ import annotations

import time

import retico_core
from retico_core.audio import AudioIU

from vizij_retico.hub import WebSocketHub
from vizij_retico.web_input import WebInputModule

RATE = 16000
WIDTH = 2
BLOCK_MS = 8  # what the browser worklet posts
SECONDS = 6.0


class _Counter(retico_core.AbstractModule):
    """Stands in for GoogleASRModule: same base class, so the same loop throttle."""

    @staticmethod
    def name() -> str:
        return "Counter"

    @staticmethod
    def description() -> str:
        return "Counts audio it receives."

    @staticmethod
    def input_ius():
        return [AudioIU]

    @staticmethod
    def output_iu():
        return AudioIU

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.frames = 0
        self.messages = 0

    def process_update(self, update_message):
        self.messages += 1
        for iu, ut in update_message:
            if ut == retico_core.UpdateType.ADD:
                self.frames += 1
        return None


def _feed_realtime(hub: WebSocketHub, seconds: float) -> int:
    """Post 8 ms blocks at real time, as the browser does. Returns ms of audio sent."""
    block = b"\x00" * (RATE * BLOCK_MS // 1000 * WIDTH)
    n = int(seconds * 1000 / BLOCK_MS)
    start = time.monotonic()
    for i in range(n):
        hub.audio_in.put(block)
        # Pace against the clock rather than sleeping a fixed amount, so a slow machine
        # doesn't silently send less audio than the test claims.
        target = start + (i + 1) * BLOCK_MS / 1000
        drift = target - time.monotonic()
        if drift > 0:
            time.sleep(drift)
    return n * BLOCK_MS


def test_consumer_keeps_up_with_realtime_audio():
    hub = WebSocketHub()
    web_in = WebInputModule(hub)
    counter = _Counter()
    web_in.subscribe(counter)

    web_in.run()
    counter.run()
    try:
        sent_ms = _feed_realtime(hub, SECONDS)
        # Let the tail drain; generous, since the point is throughput not latency.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if counter.frames * 10 >= sent_ms * 0.95:
                break
            time.sleep(0.1)
    finally:
        web_in.stop()
        counter.stop()

    received_ms = counter.frames * 10  # frame_ms=10
    ratio = received_ms / sent_ms
    print(
        f"\n  sent {sent_ms} ms in {SECONDS:.0f}s | received {received_ms} ms "
        f"({ratio:.0%}) across {counter.messages} messages "
        f"({received_ms / max(counter.messages, 1):.0f} ms/message)"
    )

    # The regression this guards: per-frame messages cap the consumer at ~50 % of real
    # time. Anything at or below that means the batching is gone.
    assert ratio > 0.9, (
        f"consumer received only {ratio:.0%} of the audio — it is falling behind "
        f"real time ({counter.messages} messages for {sent_ms} ms of audio)"
    )
    # And the mechanism: many frames per message, not one.
    assert received_ms / max(counter.messages, 1) > 30, (
        "audio is being delivered roughly one frame per UpdateMessage; the consumer's "
        "20 ms loop will starve on this"
    )
