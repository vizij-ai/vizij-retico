"""Echo rejection and barge-in, through the real gate.

Two failure modes, opposite in cost:
  - letting the agent's own voice through -> it answers itself, forever
  - dropping the user's voice           -> it goes deaf, which is what we just fixed

So both directions are asserted here, and the gate is driven the way the graph drives it
(whole UpdateMessages, real IU types) rather than by poking its internals.
"""

from __future__ import annotations

import retico_core
from retico_core.text import SpeechRecognitionIU

from vizij_retico.asr_switch import AsrGate

AGENT_LINE = "Octopuses have three hearts and blue blood, which helps in cold water."


class _FakeGoogle:
    """source_of() keys off the creator's class name; IUs need `.id` from their creator."""

    _n = 0

    def __init__(self) -> None:
        _FakeGoogle._n += 1
        self.id = f"fake-google-{_FakeGoogle._n}"


def _message(text: str, final: bool = True) -> retico_core.UpdateMessage:
    um = retico_core.UpdateMessage()
    words = text.split()
    prev = None
    for i, word in enumerate(words):
        iu = SpeechRecognitionIU(creator=_FakeGoogle(), previous_iu=prev)
        iu.set_asr_results([word], word, 0.0, 1.0, False)
        iu.simulated = False
        um.add_iu(iu, retico_core.UpdateType.ADD)
        prev = iu
    if final:
        commit = SpeechRecognitionIU(creator=_FakeGoogle(), previous_iu=prev)
        commit.set_asr_results([text], text, 0.0, 1.0, True)
        commit.simulated = False
        um.add_iu(commit, retico_core.UpdateType.COMMIT)
    return um


def _gate(speaking: bool, spoken: str = AGENT_LINE):
    fired = []
    g = AsrGate(
        get_source=lambda: "google",
        is_speaking=lambda: speaking,
        recent_spoken=lambda: spoken,
        on_barge_in=lambda: fired.append(True),
    )
    return g, fired


def test_agent_voice_is_dropped_and_does_not_barge_in():
    gate, fired = _gate(speaking=True)
    out = gate.process_update(_message("octopuses have three hearts and blue blood"))
    assert out is None, "the agent's own voice reached the dialogue graph"
    assert not fired, "hearing itself must not count as an interruption"


def test_user_interrupting_passes_and_fires_barge_in():
    gate, fired = _gate(speaking=True)
    out = gate.process_update(_message("wait stop I meant something else"))
    assert out is not None, "the user was talking and got dropped"
    assert fired, "talking over the agent should interrupt it"


def test_normal_turn_when_not_speaking_is_untouched():
    gate, fired = _gate(speaking=False)
    out = gate.process_update(_message("tell me about squid"))
    assert out is not None
    assert not fired, "nothing to interrupt when the agent is silent"


def test_whole_utterance_is_dropped_not_fragments():
    """A dropped COMMIT with surviving ADDs strands words in the accumulator, which then
    get prepended to the user's next turn. Drop all or nothing."""
    gate, _ = _gate(speaking=True)
    out = gate.process_update(_message("have three hearts and blue blood"))
    assert out is None
    # And the inverse: when it passes, the COMMIT must come with it.
    gate2, _ = _gate(speaking=True)
    out2 = gate2.process_update(_message("something completely different please"))
    kinds = {ut for _, ut in out2}
    assert retico_core.UpdateType.COMMIT in kinds, "forwarded ADDs without their COMMIT"


def test_simulated_turns_always_pass():
    gate, _ = _gate(speaking=True)
    um = _message("octopuses have three hearts")  # would otherwise be judged echo
    for iu, _ut in um:
        iu.simulated = True
    assert gate.process_update(um) is not None, "the debug harness must keep working"


def test_inactive_source_is_still_dropped():
    gate = AsrGate(get_source=lambda: "browser", is_speaking=lambda: False)
    assert gate.process_update(_message("hello there")) is None
