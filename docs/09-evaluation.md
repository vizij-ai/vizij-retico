# 09 · Evaluation

The workshop's Topic 03 explicitly asks for *"good practices to evaluate dialogue systems,
including evaluation metrics."* A systems/demo paper does not need a full user study, but a few
**objective, cheaply-measurable** numbers make the contribution concrete and pre-empt the obvious
reviewer question ("is it actually real-time / in-sync?"). All metrics below are instrumentable
from data the system already produces.

## 9.1 Metric 1 — end-to-end latency (responsiveness)

**Claim it supports:** the bridge renders incremental signals fast enough to read as responsive.

**Definition.** For each social-signal event (turn/backchannel/nod/gaze), latency =
`t_applied_on_face − t_emit_in_retico`, decomposed where possible into:
- `t_emit` — stamped in the bridge envelope (`ts`).
- `t_recv` — driver receipt time (add on the client).
- `t_applied` — when the driver starts the tween (client).

**Method.** The driver logs `(seq, type, t_emit, t_recv, t_applied)`; compute `t_recv − t_emit`
(transit) and `t_applied − t_recv` (dispatch). Report median + p95 over a vignette run.

**Target.** median end-to-end < ~150 ms for social signals on a local/LAN setup.

## 9.2 Metric 2 — time-to-first-backchannel (incrementality payoff)

**Claim it supports:** incrementality produces earlier social feedback than a turn-based system —
the core reason for using retico.

**Definition.** Within a listening segment, the elapsed time from a backchannel-appropriate moment
(or from utterance onset) to the agent's first rendered backchannel/nod, compared between:
- **Incremental** (our system): MaAI fires mid-utterance.
- **Turn-based baseline**: the same pipeline but the agent may only react after end-of-utterance
  (silence-gated). Implemented by gating the bridge's social events on `speech.end`/VAD silence.

**Method.** Replay the *same* recorded audio (Vignette 1) through both configurations (the
`--record`/replay path makes this deterministic); measure the delta. Expect the incremental system
to produce feedback hundreds of ms to seconds earlier, and multiple backchannels where the
baseline produces one-at-the-end or none.

**Presentation.** A side-by-side timeline figure (incremental vs baseline) over the identical
utterance — visually compelling and quantitatively simple.

## 9.3 Metric 3 — viseme–audio synchronization error (lip-sync fidelity)

**Claim it supports:** the reused client-side viseme path stays acceptably in sync (and Polly, if
used, improves it).

**Definition.** Offset between viseme onset and the corresponding audio energy/phoneme onset.

**Method (lightweight).** From the recorded audio + the driver's viseme schedule, compare viseme
onset times against audio-derived phoneme/energy onsets (the `phoneme-core` `audioPhonemeScorer`
already extracts audio features; reuse it offline). Report mean absolute offset and the fraction
within a ±X ms window. Compare Option A (baseline) vs Option A (align) vs Option B (Polly) if
multiple are wired.

**Target/framing.** Report honestly; if baseline alignment is loose, present align/Polly as the
fidelity path (see [07 §7.8](07-capabilities.md#78-known-gaps--honesty-for-the-paper)).

## 9.4 Metric 4 — robustness / throughput (systems soundness)

**Claim it supports:** the bridge holds up under real incremental churn (ADD/REVOKE storms).

**Method.** Log event rate (events/s) per type during a vignette; log REVOKE handling (how many
in-flight impulses were cancelled vs already-played); confirm no dropped frames (`seq` gaps) and no
gaze jitter (visual + a channel-value trace via `useVizijOutputs`). Report peak events/s and that
the face remained smooth.

## 9.5 Optional — qualitative / subjective (only if time)

If a small subjective read is wanted (not required for a 4-page systems paper):
- 3–5 viewers rate short clips (incremental vs baseline; with vs without gaze) on naturalness /
  responsiveness (single Likert item each). Report as indicative, not a study.
- Keep it clearly scoped as a pilot; the workshop is non-archival and demo-oriented.

## 9.6 Instrumentation checklist

- Bridge `--record` → JSONL of every emitted event (with `ts`, `seq`).
- Driver logging → `(seq, type, t_recv, t_applied)` + optional channel-value trace.
- Deterministic **replay** of a recorded audio file through the retico network for A/B runs.
- A "turn-based baseline" flag on the bridge (gate social events on end-of-utterance).
- Offline analysis script (Python/notebook) that reads the JSONL(s) + audio and emits the three
  figures (latency distribution, incremental-vs-baseline timeline, viseme-offset histogram).

## 9.7 What we do *not* claim

- Not a comparison of ASR/TTS/LLM quality (those are swappable, off-the-shelf).
- Not an improvement to MaAI's prediction accuracy (we render its predictions, we don't retrain).
- Not a full HRI user study. The contribution is the *system* and its timing/coherence properties;
  the metrics substantiate exactly that and nothing more.
