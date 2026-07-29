"""Echo rejection has to be right in both directions.

A false positive drops real user speech — the exact failure this replaces. A false
negative just lets one echoed phrase through. The cases below are written from what the
recognizer actually does to speaker output: it drops words, mangles a few, and rarely
returns the sentence cleanly.
"""

from __future__ import annotations

from vizij_retico.echo import is_echo, overlap

AGENT = "Octopuses have three hearts and blue blood, which helps them in cold water."


def _check(cases):
    bad = []
    for heard, want, why in cases:
        got = is_echo(heard, AGENT)
        if got != want:
            bad.append(f"  {'echo' if want else 'user'} expected, got "
                       f"{'echo' if got else 'user'}: {heard!r}  ({why}, "
                       f"overlap={overlap(heard, AGENT):.2f})")
    assert not bad, "\n" + "\n".join(bad)


def test_agent_hearing_itself_is_rejected():
    _check([
        (AGENT, True, "clean loopback"),
        ("octopuses have three hearts and blue blood", True, "partial pickup"),
        ("three hearts and blue blood which helps them", True, "mid-sentence pickup"),
        ("have three hearts blue blood cold water", True, "dropped words"),
        ("OCTOPUSES HAVE THREE HEARTS", True, "case differences"),
        ("hearts, and blue blood!", True, "punctuation differences"),
    ])


def test_real_user_speech_is_never_dropped():
    _check([
        ("stop", False, "one-word interruption"),
        ("wait", False, "one-word interruption"),
        ("hold on", False, "two-word interruption"),
        ("tell me more about that", False, "unrelated follow-up"),
        ("what about squid", False, "related but new"),
        ("that's amazing, tell me about their blood", False,
         "shares 'blood' but is mostly new"),
        ("do they really have three hearts", False,
         "quotes the agent but adds a question — a human would say this"),
        ("no I meant something else entirely", False, "correction"),
    ])


def test_nothing_spoken_means_nothing_is_echo():
    assert not is_echo("octopuses have three hearts", "")
    assert not is_echo("", AGENT)
