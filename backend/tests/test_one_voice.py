"""Only one voice, ever.

Reported symptom: "two voices responding with different things". Two independent causes,
both reproduced here:

  1. Clauses of one reply overlapped. The backend streams them ~0.3 s apart while each is
     several seconds of audio, and the browser started each on arrival. (The queue that
     fixes this lives in the driver; what's asserted here is the backend contract it
     relies on — clauses arrive as separate events and must be played in order.)
  2. After a barge-in, clauses still streaming from the interrupted reply were stamped
     with the *new* generation and spoken alongside the new reply.
"""

from __future__ import annotations

import time

import retico_core
from retico_core.text import GeneratedTextIU

from vizij_retico.tts_module import TTSModule


class _Creator:
    id = "test-llm"


_iuid = iter(range(1, 10_000))


def _clause(text: str) -> retico_core.UpdateMessage:
    # iuid must be supplied: IncrementalUnit defines __eq__, so __hash__ is None, and its
    # __init__ falls back to hash(self) when no iuid is given. Modules avoid this by
    # going through create_iu().
    iu = GeneratedTextIU(creator=_Creator(), iuid=next(_iuid))
    iu.payload = text
    iu.text = text
    # from_iu() puts the IU in a set; GeneratedTextIU isn't hashable here, so build the
    # message directly the way the module's own callers effectively do.
    um = retico_core.UpdateMessage()
    um.add_iu(iu, retico_core.UpdateType.ADD)
    return um


def _module():
    spoken: list[str] = []
    tts = TTSModule(say=lambda t: (time.sleep(0.05), spoken.append(t))[1])
    return tts, spoken


def test_clauses_of_one_reply_are_all_spoken_in_order():
    tts, spoken = _module()
    tts.begin_reply()
    for c in ("First clause.", "Second clause.", "Third clause."):
        tts.process_update(_clause(c))
    time.sleep(0.6)
    assert spoken == ["First clause.", "Second clause.", "Third clause."], spoken


def test_barge_in_silences_the_rest_of_the_interrupted_reply():
    """The bug: late clauses inherited the post-cancel generation and were spoken."""
    tts, spoken = _module()
    tts.begin_reply()
    tts.process_update(_clause("Octopuses have three hearts."))
    time.sleep(0.15)  # let the worker take it

    tts.cancel()  # user interrupts here

    # The LLM is still streaming the interrupted reply; these must NOT be spoken.
    tts.process_update(_clause("They can taste with their arms."))
    tts.process_update(_clause("They have nine brains."))
    time.sleep(0.4)

    leaked = [s for s in spoken if "arms" in s or "brains" in s]
    assert not leaked, f"interrupted reply kept talking: {leaked}"


def test_the_next_reply_speaks_normally_after_a_barge_in():
    tts, spoken = _module()
    tts.begin_reply()
    tts.process_update(_clause("Interrupted sentence."))
    tts.cancel()
    tts.process_update(_clause("Still from the old reply."))

    tts.begin_reply()  # the new turn starts
    tts.process_update(_clause("Fresh answer."))
    time.sleep(0.4)

    assert "Fresh answer." in spoken, spoken
    assert "Still from the old reply." not in spoken, spoken


def test_repeated_barge_ins_do_not_wedge_it():
    tts, spoken = _module()
    for i in range(3):
        tts.begin_reply()
        tts.process_update(_clause(f"reply {i} clause."))
        tts.cancel()
    tts.begin_reply()
    tts.process_update(_clause("final answer."))
    time.sleep(0.4)
    assert "final answer." in spoken, spoken
