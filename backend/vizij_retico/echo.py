"""Telling the agent's own voice apart from the user's, by text rather than by clock.

The microphone hears the agent through the speakers, the server-side ASR transcribes it
happily, and the agent then answers itself — a loop that sustains on its own. Browser
echo cancellation reduces this but does not remove it, especially on speakers.

The obvious guard is to mute the ASR while the agent talks. That works, and it was the
first approach here, but it also makes barge-in impossible: you cannot interrupt something
that is not listening. And it was fragile in practice — the mute deadline had to be
estimated from a dispatch-time guess at playback duration, which was wrong in both
directions (167 s on one path, too short on another).

So compare *content* instead. If what we just heard is largely made of words the agent is
currently saying, it is echo. If it isn't, the user is talking over us, which is barge-in
and should interrupt. This has no timing dependency at all, so it cannot drift.

The asymmetry matters: a false positive silently swallows real user speech, which is the
failure we are trying to fix. A false negative merely lets one echoed phrase through, and
the agent answers something slightly odd. So the threshold is deliberately reluctant to
call something echo.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9']+")

# Fraction of the heard words that must also appear in what the agent is saying before we
# call it echo. High, because the cost of a false positive (dropping the user) is worse
# than a false negative (answering an echo once).
ECHO_THRESHOLD = 0.75

# Utterances shorter than this are never classified as echo. "stop", "wait", "no" are
# exactly the interruptions barge-in exists to catch, and they are also the most likely
# to coincidentally appear in the agent's own sentence.
MIN_TOKENS_FOR_ECHO = 3


def tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def overlap(heard: str, spoken: str) -> float:
    """Fraction of `heard`'s words that occur in `spoken` (0.0 when heard is empty).

    Bag-of-words on purpose. ASR of speaker output drops and reorders words, so requiring
    a contiguous match would miss most real echo.
    """
    heard_tokens = tokens(heard)
    if not heard_tokens:
        return 0.0
    spoken_tokens = set(tokens(spoken))
    if not spoken_tokens:
        return 0.0
    hits = sum(1 for t in heard_tokens if t in spoken_tokens)
    return hits / len(heard_tokens)


def is_echo(heard: str, spoken: str) -> bool:
    """True if `heard` looks like the agent hearing `spoken` come back at it."""
    heard_tokens = tokens(heard)
    if len(heard_tokens) < MIN_TOKENS_FOR_ECHO:
        return False
    return overlap(heard, spoken) >= ECHO_THRESHOLD
