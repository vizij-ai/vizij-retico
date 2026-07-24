# 11 · Paper outline (author support)

> The paper is written by the author. This is scaffolding — a suggested structure, the argument
> spine, and which artifacts/figures support each part — for a **4-page IEEE two-column**
> systems/demonstration paper (fits within the 4–8 page "paper" band; also compressible to a 2–4
> page extended abstract by trimming §IV–V). Non-archival; IROS 2026 HRD workshop.

## Title (options)
- "Rendering Incremental Dialogue on an Expressive Face: A retico–Vizij Bridge for Multimodal HRI"
- "From Incremental Units to Faces: Real-Time Gaze, Emotion, and Lip-Sync for Situated Dialogue"

## Abstract (~150 words)
Problem: language alone is not sufficient for embodied dialogue; timing and non-verbal modalities
matter. Approach: bridge retico's incremental dialogue signals (turn-taking, backchannel, nod
via VAP; ASR/LLM/TTS; FER) to Vizij's real-time expressive face through one WebSocket protocol and
an editable IU→animation mapping. Contribution: the bridge + mapping render six behaviors
(turn-taking, backchannel, nod, lip-sync, emotion, gaze) as coherent, well-timed social behavior,
with a gaze-arbitration policy that keeps them from conflicting. Results: sub-150 ms social-signal
latency; earlier feedback than a turn-based baseline; acceptable lip-sync. A portable expressive
layer whose value stream also targets a physical robot (Quori).

## I. Introduction & motivation (Topics 01, 04) — ~0.75 col
- Turn-based, unimodal agents feel latent and flat; conversation is incremental and multimodal.
- Pose the Topic-04 question verbatim ("is language sufficient…?") and answer: add gaze, emotion,
  backchannels, nods, lip-sync — and *time them incrementally*.
- Contribution bullets (bridge, protocol, editable mapping, arbitration, evaluation, Quori path).

## II. Background & related work — ~0.75 col
- Incremental dialogue / IU model (Schlangen & Skantze 2011); retico (Michael 2020); MaAI/VAP
  turn-taking; backchannel/nod prediction.
- Expressive agent faces / robot faces; embodiment in HRI; (Skantze/Furhat, situated dialogue).
- Position: prior work does incrementality *or* expressive rendering; we contribute the glue that
  makes incremental signals drive a face coherently, as reusable infrastructure.

## III. System (the core — Topic 02/04) — ~1.5 col + Fig 1
- Architecture (Fig 1): retico network → `VizijWebSocketModule` → browser `registerInputDriver` →
  Arora device store → face. Note MaAI-parallel-to-ASR for low latency.
- The bridge as contribution: fan-in of heterogeneous IU streams into one protocol that preserves
  ADD/REVOKE/COMMIT over the wire (Fig references [03](03-websocket-protocol.md)).
- The IU→animation mapping (Fig 2): editable table; `animateValue`-vs-`setInput` policy;
  gaze arbitration (`joint_attention > aversion > turn > idle`); impulses riding on posture. This
  is the intellectual core — emphasize the *temporal* mapping, not just the semantic one.
- Lip-sync choice (Fig 3): reuse client-side viseme engine; Polly as fidelity upgrade.
- Stack in one sentence + the local/CPU/no-key default vs cloud-for-latency note.

## IV. Demonstration — ~0.5 col + a vignette figure
- The three vignettes (Listener / Speaker / Empathic Mirror) and which capabilities each
  foregrounds ([08](08-demo-vignettes.md)). One timeline figure from "The Listener" showing social
  signals landing mid-utterance.

## V. Evaluation — ~0.5 col + 1–2 figures
- Latency distribution; time-to-first-backchannel vs turn-based baseline (the key figure);
  viseme–audio offset ([09](09-evaluation.md)). Keep claims tight and honest.

## VI. Limitations & future work — ~0.25 col
- Screen vs physical embodiment → **Quori** deployment (same value stream to a robot face);
  categorical FER; heuristic baseline visemes; joint-attention target source; no user study yet.

## VII. Conclusion — ~2–3 sentences
- Reusable bridge turning incremental dialogue into coherent multimodal facial behavior; a step
  toward embodied agents that *listen* visibly, not just speak.

## Figures (all in [`figures/`](figures/))
- **Fig 1** `01_architecture` — system architecture (with cloud-key callout).
- **Fig 2** `02_mapping` — IU → WebSocket event → Vizij channel (verb/duration).
- **Fig 3** `03_visemes` — client-side vs Polly viseme paths.
- **Fig 4** (to generate at milestone 9) — Listener timeline: incremental vs turn-based baseline.
- Optional Fig 5 — latency histogram; Fig 6 — viseme-offset histogram.

## Framing reminders (from [01](01-motivation-and-workshop.md))
- Lead with multimodality + incremental timing; name Quori; connect to embodied HRI.
- Audience skews physical-robot — do not pitch it as "an animation demo"; pitch it as
  infrastructure for timing-critical multimodal HRI output.

## Length management
- 4-page target: keep §II and §V tight; push protocol/mapping detail to this repo's docs and cite
  informally ("full protocol in the system's documentation").
- 2–4 page extended-abstract variant: merge §IV–V into one "Demonstration & preliminary results"
  section and drop one figure.
