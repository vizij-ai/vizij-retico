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

from typing import Any, Optional

import retico_core

from .events import EventFramer, iu_provenance

# --- tunable thresholds -------------------------------------------------------
VAD_ACTIVE = 0.5          # channel-1 vad above this => user is speaking
SHIFT_HI = 0.5            # p_shift above this => a turn shift is likely
BC_THRESHOLD = 0.6        # p_bc rising edge above this => backchannel cue
NOD_THRESHOLD = 0.6       # p_nod_* rising edge above this => nod cue


class MaaiClassifiers:
    """Stateful (edge-detecting) classifiers, exposed as a name→fn registry."""

    def __init__(self) -> None:
        self._bc_armed = True
        self._nod_armed = True
        self._asr_tokens: list[str] = []

    @property
    def registry(self) -> dict[str, Any]:
        return {
            "VAPIU": self.turn_state,
            "BackchannelIU": self.backchannel,
            "NodIU": self.nod,
            "SpeechRecognitionIU": self.asr_text,
        }

    # -- ASR (Whisper) --------------------------------------------------------
    def asr_text(self, iu, ut, framer: EventFramer) -> Optional[dict[str, Any]]:
        """Accumulate incremental ASR tokens into a running transcript.

        WhisperASRModule emits one SpeechRecognitionIU token per ADD and COMMITs at
        end-of-utterance. (Approximate: REVOKEs are ignored for the MVP.)
        """
        token = (getattr(iu, "text", "") or "").strip()
        if ut == retico_core.UpdateType.ADD:
            if token:
                self._asr_tokens.append(token)
            partial = " ".join(self._asr_tokens)
            if not partial:
                return None
            return framer.frame(
                "asr.text", {"text": partial, "final": False}, iu=iu_provenance(iu, ut)
            )
        if ut == retico_core.UpdateType.COMMIT:
            text = " ".join(self._asr_tokens)
            self._asr_tokens = []
            if not text:  # ignore empty commits from trailing silence
                return None
            return framer.frame(
                "asr.text", {"text": text, "final": True}, iu=iu_provenance(iu, ut)
            )
        return None

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

        if user_vad > VAD_ACTIVE:
            state = "user_yielding" if p_shift > SHIFT_HI else "user_speaking"
        elif p_shift > SHIFT_HI:
            state = "agent_should_speak"
        else:
            state = "mutual_silence"

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
