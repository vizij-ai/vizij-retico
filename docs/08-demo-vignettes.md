# 08 · Demo vignettes

All three vignettes run on the **same** built system. A small on-screen mode toggle (or simply
scripted human behavior) foregrounds each. Each is ~20–30 s, recorded for the poster and for the
paper's figures. Together they exercise all four capabilities and visibly show the bridge routing
independent IU streams to one coherent face.

The point of using short scripted vignettes (rather than one long free interaction) is
controllability and legibility: each vignette isolates a capability cluster so a viewer — and a
reviewer — can *see* what the system does, and so the same script can be replayed for
before/after and baseline comparisons.

## 8.1 Vignette 1 — "The Listener"

**Goal:** foreground incremental listener behavior (turn-taking, backchannel, nod, mutual gaze)
while the human speaks and the agent stays silent.

**Script.** A person speaks for ~30 s (e.g. recounting a plan with natural disfluencies and
clause boundaries). The agent does not talk.

**What the audience sees.**
- Sustained **mutual gaze** with natural micro-saccades (turn posture).
- **Nods** at clause boundaries; **brow-flash / "mm" backchannels** at continuer moments — several
  of them arriving *before* the speaker finishes a sentence.
- A slight **anticipatory brow raise / lean** as `p_shift` rises near a yield point.

**Capabilities:** turn-taking, backchannel, nod, gaze (+ a faint mirrored expression if FER on).
**Why it's the money shot:** it is the clearest demonstration of *incrementality* — social signals
timed to the ongoing utterance, which a turn-based system structurally cannot produce. Lowest
technical risk (no LLM/TTS in the loop).

**Evaluation hook:** time-to-first-backchannel vs a turn-based baseline (see [09](09-evaluation.md)).

## 8.2 Vignette 2 — "The Speaker"

**Goal:** foreground agent output — turn hand-off, lip-sync, and expressive speech.

**Script.** The human asks a short question ("Can you help me plan my week?"). The agent takes the
turn and replies in 1–2 sentences with content that carries affect (e.g. briefly *concerned*, then
*reassuring*).

**What the audience sees.**
- A visible **turn hand-off**: gaze hold + blink as the agent takes the floor; a brief **aversion**
  ("thinking") while the LLM produces the reply, then back to the user.
- **Lip-synced** speech (viseme mouth shapes matched to the TTS audio).
- **Emotional expression** matched to the reply content (`emotion.affect`: concerned → reassuring),
  attack/hold/decay.

**Capabilities:** turn-taking (hand-off + aversion), lip-sync, agent emotion, gaze.
**Risk:** depends on ASR→LLM→TTS latency; use a cloud LLM for the recording to keep the hand-off
crisp.

**Evaluation hook:** viseme–audio sync offset; hand-off latency.

## 8.3 Vignette 3 — "The Empathic Mirror"

**Goal:** foreground perception-driven behavior — FER mirroring and gaze coordination.

**Script.** Webcam on. The user smiles, then frowns, then looks off to the side at an object.

**What the audience sees.**
- The agent **mirrors** the user's expression (FER → expression), smoothly and with hysteresis
  (no twitching).
- Sustained **mutual gaze** while the user faces the camera.
- A shift to **joint attention** (eyes + head toward the target) when the user looks away, then
  back to mutual gaze. *(MVP note: the joint-attention target may be scripted; mark it as such —
  see [07 §7.8](07-capabilities.md#78-known-gaps--honesty-for-the-paper).)*

**Capabilities:** emotion (FER mirror), gaze (mutual + joint attention).
**Risk:** FER noise (mitigated by hysteresis); needs a webcam.

**Evaluation hook:** FER→expression latency; qualitative gaze-coordination judgement.

## 8.4 Recording notes

- Fixed camera framing on the face; consistent lighting; show the human (or their audio) so the
  timing relationship is legible.
- Capture the debug overlay (connection status, `seq`, latency) in at least one take for the paper
  figure, and a clean take without it for the poster loop.
- Record the **event JSONL** (bridge `--record`) alongside each take so a) the figure timelines are
  exact and b) the vignette can be replayed deterministically for the baseline comparison.
- Keep a **turn-based baseline** take of Vignette 1 (agent reacts only after end-of-utterance) for
  the side-by-side that makes the incrementality point quantitatively.

## 8.5 Mapping vignettes → milestones

- Vignette 1 demoable after milestone 4 (turn/backchannel/nod + gaze).
- Vignette 2 demoable after milestone 5 (speaking path + affect).
- Vignette 3 demoable after milestone 6 (FER + gaze arbiter).
See [10](10-build-plan.md).
