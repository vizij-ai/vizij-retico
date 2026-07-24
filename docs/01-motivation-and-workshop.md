# 01 · Motivation & workshop fit

## 1.1 The problem

Spoken dialogue with an embodied agent is not just a text exchange. Humans coordinate
conversation through a dense layer of *non-verbal, incremental* behavior: we look at our
partner while they speak and glance away while planning a reply; we nod and say "mm-hm" to
signal we're following; we begin to react to an utterance *before it finishes*; our faces
carry affect that colors the words. Most conversational-agent stacks discard this layer.
They are **turn-based** (wait for a complete utterance, then respond) and **unimodal** (text
in, text/speech out), which produces agents that feel latent, flat, and socially inert.

Two capabilities are needed to fix this, and they usually live in different worlds:

1. **Incremental, multimodal dialogue processing** — the ability to emit partial and revisable
   signals in real time (not only "the user said X" but "the user is *still* speaking," "a turn
   shift is likely in 400 ms," "this is a good moment to backchannel"). This is the domain of
   **retico**.
2. **Real-time expressive rendering** — a face that can be driven continuously and smoothly on
   many channels at once (gaze direction, eyelids, brow, jaw, per-viseme mouth shapes, emotion
   blends). This is the domain of **vizij-web**.

`vizij-retico` joins them and asks the workshop's central multimodality question directly: *once
you have rich incremental dialogue signals, what does it take to render them as coherent social
behavior on an embodied face, and does doing so improve the interaction?*

## 1.2 Why retico and vizij specifically

**retico's differentiators.**
- *True incrementality.* The Incremental Unit (IU) model (Schlangen & Skantze, 2011) gives every
  module ADD/REVOKE/COMMIT semantics, so downstream consumers can react to hypotheses and
  gracefully revise when they change (e.g. an ASR word is revoked). Latency to first reaction is
  bounded by the *signal*, not the *utterance*.
- *Social signals as first-class modules.* `retico-maai` exposes Voice Activity Projection
  (turn-taking), backchannel prediction, and nod prediction as live streams. Few open dialogue
  toolkits provide these at all, let alone as swappable modules.
- *Modularity.* ASR/TTS/LLM/vision backends are interchangeable, which makes controlled
  comparisons (the kind reviewers ask for) straightforward.

**vizij-web's differentiators.**
- *A value-driven real-time runtime.* The face is driven by writing values to named channels in
  a shared store; a behavior graph turns those into rig deformations every tick. This is exactly
  the shape an external, streaming controller wants to target.
- *Rich expressive channels.* Standard feature spaces for eyes, eyelids, brow, jaw, head, plus
  pose-weight blendshapes for emotions and visemes.
- *Existing conversational scaffolding to reuse.* A working client-side viseme engine
  (`phoneme-core` + `useVisemeMouth`) and gaze/emotion tool logic (`useAgentFaceTools`) already
  exist and can be reused rather than reinvented.

**The gap that becomes our contribution.** retico has no viseme module and no websocket module;
vizij has no notion of incremental dialogue. The bridge — protocol + mapping + driver — is where
the intellectual work lives (see [04](04-iu-animation-mapping.md)).

## 1.3 The workshop

- **Venue:** Human–Robot Dialogue (HRD) workshop, co-located with **IROS 2026**, Pittsburgh,
  **Oct 1, 2026** (half-day).
- **Submission:** 2–4 page extended abstracts or 4–8 page papers; **IEEE two-column** template;
  **non-archival**; via OpenReview. **Deadline Aug 3, 2026.**
- **No dedicated demo/video track** — a system is presented by submitting a paper and showing it
  at the poster session / contributed talk. Our target is a **4-page systems/demo paper** plus a
  set of short recorded vignettes.

### Topics of interest and where we fit

The CFP groups topics into five themes. Our strongest anchors:

- **Topic 04 — "Human-X dialogue informs human-robot dialogue."** Contains the bullet *"Is
  language a sufficient modality for human-robot communication? What other modalities can help,
  and how?"* This is a near-verbatim description of our contribution: adding gaze, emotion,
  backchannels, nods, and lip-sync as non-linguistic modalities and showing how they are produced
  and timed. **Primary fit.**
- **Topic 03 — "Robot learning & evaluation."** Contains *"good practices to evaluate dialogue
  systems, including evaluation metrics and benchmark datasets."* Our lightweight evaluation
  (latency, time-to-first-backchannel vs a turn-based baseline, viseme–audio sync error) lands
  here. See [09](09-evaluation.md).
- **Topic 01 — Motivation.** *"How can dialogue improve HRI / reduce ambiguity"* frames the intro.
- **Topic 02 — Robotic language grounding.** Weaker, but the generation→rendering pipeline touches
  *"generate language from a model of language and the environment."*

### Audience calibration (important)

The workshop skews toward **physical-robot learning** (references to RT-X/Droid/Bridge robot
datasets; foundation/vision-language models for manipulation; organizers from robot-learning
groups). An on-screen animated face is a **screen-embodied** conversational agent, which sits at
the edge of that scope. To land well:

- Lead with **multimodality and incremental timing**, not animation for its own sake.
- Explicitly connect avatar behaviors to **embodied HRI**, and name **Quori** as the intended
  physical endpoint (the same value stream that drives the web face can drive a robot face). This
  turns "it's just a screen avatar" into "it's a portable expressive layer with a physical target."
- Note the receptive sub-audience: panelists include **Gabriel Skantze** (turn-taking / Furhat),
  **Bahar Irfan** (social robots), and **Matthew Marge** (situated dialogue) — all of whom value
  the conversational-agent / multimodal-timing angle even though turn-taking and backchannels are
  not written verbatim in the topic list.

## 1.4 Scope for the MVP

- One built system; **four capabilities** demonstrated (turn-taking/backchannel/nod, lip-sync/
  visemes, emotion, gaze).
- **Vizij web face only** for now; Quori is future work in the paper.
- Default stack runs **local/CPU/no-key**; cloud keys are available and used where they clearly
  help (LLM latency for the recorded demo; optional Polly visemes).
- Deliverable of the engineering work: the running system + the figures/numbers the paper draws
  on. **The paper itself is written by the author, not generated here.**

## 1.5 Claimed contribution (one sentence)

> We connect an incremental spoken-dialogue system (retico) to a real-time expressive 3D face
> (Vizij) through a WebSocket bridge and an editable IU→animation mapping that renders
> turn-taking, backchannels, nods, lip-sync, emotion, and gaze as coherent, well-timed social
> behavior — a portable expressive layer whose value stream also targets a physical robot (Quori).
