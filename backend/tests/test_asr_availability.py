"""An ASR option must be offered only if the running graph can actually produce it.

The bug this pins: a dev venv with the `full` extras has retico-whisperasr importable, so
Whisper advertised itself even when the backend was started in `lite` mode — whose graph
builds no Whisper module. Selecting it pointed the gate at a source nothing feeds and the
app went deaf. Nothing raised, nothing logged; the UI cheerfully showed "Whisper (local)".

    PYTHONPATH=. ./.venv/bin/python tests/test_asr_availability.py
"""

from __future__ import annotations

import sys

from vizij_retico import providers


def available(kind: str, pid: str) -> bool:
    spec = providers.get(kind, pid)
    return spec is not None and spec.available


def main() -> int:
    bad = []

    # The lite graph wires the browser recognizer and Google STT, and nothing else.
    providers.set_wired_asr({"browser", "google"})
    if available("asr", "whisper"):
        bad.append("lite graph: whisper offered, but no Whisper module is built")
    if not available("asr", "browser"):
        bad.append("lite graph: browser should always be selectable")

    # The maai graph can build Whisper lazily, so it is a real option there — provided
    # the package is actually installed.
    providers.set_wired_asr({"browser", "google", "whisper"})
    import importlib.util

    installed = importlib.util.find_spec("retico_whisperasr") is not None
    if available("asr", "whisper") != installed:
        bad.append(
            f"maai graph: whisper available={available('asr', 'whisper')} "
            f"but installed={installed}"
        )

    # A source the graph does not wire is never available, whatever is installed.
    providers.set_wired_asr({"browser"})
    if available("asr", "google"):
        bad.append("google offered while unwired")

    for line in bad:
        print("FAIL:", line)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
