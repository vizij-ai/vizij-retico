"""Classifiers: retico-maai prediction IUs → Vizij protocol events.

MaAI IU payloads (from retico-maai / upstream maai):
- VAPIU:         payload = { "<creator_id> (1)": {p_now, p_future, vad}, "<...> (2)": {...} }
                 channel 1 = the real (browser) source; channel 2 = zero-fed (agent).
- BackchannelIU: payload = { "p_bc": float }
- NodIU:         payload = { "p_bc", "p_nod_short", "p_nod_long", "p_nod_long_p" }

These are continuous per-frame (~10 Hz) probabilities with no discrete labels, so we
threshold + edge-detect here and map to `turn.state` / `backchannel.cue` / `nod.cue`.
All thresholds are tunable in one place (the reticoMapping lives on the frontend; these
are the *source-side* derivations).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

import retico_core

from .events import EventFramer, iu_provenance

# --- tunable thresholds -------------------------------------------------------
VAD_ACTIVE = 0.5          # channel-1 vad above this => user is speaking
SHIFT_HI = 0.5            # p_shift above this => a turn shift is likely
YIELD_WINDOW = 2.0        # s after the user last spoke to still call it the agent's turn
BC_THRESHOLD = 0.6        # p_bc rising edge above this => backchannel cue
NOD_THRESHOLD = 0.6       # p_nod_* rising edge above this => nod cue


class MaaiClassifiers:
    """Stateful (edge-detecting) classifiers, exposed as a name→fn registry."""

    def __init__(self, on_turn_state: Optional[Callable[[str], None]] = None) -> None:
        self._bc_armed = True
        self._nod_armed = True
        self._asr_ius: list[Any] = []  # IUs of the in-progress utterance (REVOKE-aware)
        self._last_user_active = 0.0  # monotonic time the user was last speaking
        # Optional sink for the derived turn state (e.g. the LLM's floor gate).
        self._on_turn_state = on_turn_state

    @property
    def registry(self) -> dict[str, Any]:
        return {
            "VAPIU": self.turn_state,
            "BackchannelIU": self.backchannel,
            "NodIU": self.nod,
            "SpeechRecognitionIU": self.asr_text,
            "AffectIU": self.affect,
            "FerIU": self.fer,
        }

    # -- FER (the user's expression) -----------------------------------------
    def fer(self, iu, ut, framer: EventFramer) -> Optional[dict[str, Any]]:
        """FerIU (what the *user* looks like) -> emotion.fer."""
        if ut != retico_core.UpdateType.ADD:
            return None
        payload = getattr(iu, "payload", None) or {}
        if not payload.get("emotion"):
            return None
        return framer.frame("emotion.fer", dict(payload), iu=iu_provenance(iu, ut))

    # -- affect ---------------------------------------------------------------
    def affect(self, iu, ut, framer: EventFramer) -> Optional[dict[str, Any]]:
        """AffectIU (agent's own emotional state) -> emotion.affect."""
        if ut != retico_core.UpdateType.ADD:
            return None
        payload = getattr(iu, "payload", None) or {}
        if not payload.get("emotion"):
            return None
        return framer.frame("emotion.affect", dict(payload), iu=iu_provenance(iu, ut))

    # -- ASR ------------------------------------------------------------------
    def asr_text(self, iu, ut, framer: EventFramer) -> Optional[dict[str, Any]]:
        """Accumulate incremental ASR tokens into a running transcript.

        Both ASR sources emit one SpeechRecognitionIU per token (ADD) and COMMIT at
        end-of-utterance. Whisper also REVOKEs tokens when it revises a hypothesis, so
        revoked IUs must be dropped — ignoring them duplicates and garbles the
        transcript ("Nice. nice they have my Middle Eastern middle eastern ...").
        """
        if ut == retico_core.UpdateType.ADD:
            self._asr_ius.append(iu)
        elif ut == retico_core.UpdateType.REVOKE:
            # Identity-based: the gate forwards the very same IU objects.
            self._asr_ius = [held for held in self._asr_ius if held is not iu]
        elif ut == retico_core.UpdateType.COMMIT:
            text = self._joined()
            # Whisper COMMITs every token IU of the utterance, so only the first commit
            # carries text; the rest find an empty buffer and are ignored.
            self._asr_ius = []
            if not text:
                return None
            return framer.frame(
                "asr.text", {"text": text, "final": True}, iu=iu_provenance(iu, ut)
            )
        else:
            return None

        partial = self._joined()
        if not partial:
            return None
        return framer.frame(
            "asr.text", {"text": partial, "final": False}, iu=iu_provenance(iu, ut)
        )

    def _joined(self) -> str:
        return " ".join(
            t for t in ((getattr(i, "text", "") or "").strip() for i in self._asr_ius) if t
        )

    # -- turn-taking (VAP) ----------------------------------------------------
    def turn_state(self, iu, ut, framer: EventFramer) -> Optional[dict[str, Any]]:
        if ut != retico_core.UpdateType.ADD:
            return None
        entries = list((getattr(iu, "payload", None) or {}).values())
        if not entries:
            return None
        # Channel 1 is the real (browser) source; channel 2 is zero-fed by maai for
        # a single source, so its projections are meaningless. Derive turn dynamics
        # from the user's own VAP outputs: p_future falling => the user is likely to
        # yield the floor soon.
        ch1 = entries[0]
        user_vad = float(ch1.get("vad", 0.0))
        p_user = float(ch1.get("p_now", 0.0))
        user_future = float(ch1.get("p_future", 0.0))
        p_shift = round(1.0 - user_future, 4)  # likelihood the user yields soon

        # NOTE: p_shift is high during *any* silence (the user isn't about to speak), so
        # it alone can't mean "the agent's turn" — otherwise the agent would think it
        # owns the floor through all idle silence. Only call it the agent's turn shortly
        # after the user actually spoke (a real yield); sustained silence => idle.
        now = time.monotonic()
        if user_vad > VAD_ACTIVE:
            self._last_user_active = now
            state = "user_yielding" if p_shift > SHIFT_HI else "user_speaking"
        elif p_shift > SHIFT_HI and (now - self._last_user_active) < YIELD_WINDOW:
            state = "agent_should_speak"
        else:
            state = "mutual_silence"

        if self._on_turn_state is not None:
            self._on_turn_state(state)

        return framer.frame(
            "turn.state",
            {"state": state, "p_shift": round(p_shift, 4), "p_user": round(p_user, 4)},
            iu=iu_provenance(iu, ut),
        )

    # -- backchannel ----------------------------------------------------------
    def backchannel(self, iu, ut, framer: EventFramer) -> Optional[dict[str, Any]]:
        if ut != retico_core.UpdateType.ADD:
            return None
        p_bc = float((getattr(iu, "payload", None) or {}).get("p_bc", 0.0))
        # rising-edge: emit once when crossing up, re-arm when it drops back.
        if p_bc >= BC_THRESHOLD and self._bc_armed:
            self._bc_armed = False
            return framer.frame(
                "backchannel.cue",
                {"kind": "continuer", "intensity": round(p_bc, 4)},
                iu=iu_provenance(iu, ut),
            )
        if p_bc < BC_THRESHOLD * 0.8:
            self._bc_armed = True
        return None

    # -- nod ------------------------------------------------------------------
    def nod(self, iu, ut, framer: EventFramer) -> Optional[dict[str, Any]]:
        if ut != retico_core.UpdateType.ADD:
            return None
        payload = getattr(iu, "payload", None) or {}
        p_short = float(payload.get("p_nod_short", 0.0))
        p_long = float(payload.get("p_nod_long", 0.0))
        peak = max(p_short, p_long)
        if peak >= NOD_THRESHOLD and self._nod_armed:
            self._nod_armed = False
            return framer.frame(
                "nod.cue",
                {"amplitude": round(peak, 4), "count": 2 if p_long > p_short else 1},
                iu=iu_provenance(iu, ut),
            )
        if peak < NOD_THRESHOLD * 0.8:
            self._nod_armed = True
        return None
