# 07 · Capabilities

Each capability is described three ways: the **HRI grounding** (why it matters), the **retico
source** (how the signal is produced), and the **Vizij rendering** (how it appears on the face).
Together they answer the workshop's Topic-04 question — *what other modalities help, and how?*

## 7.1 Turn-taking

**HRI grounding.** Smooth turn exchange is the backbone of fluent conversation. Humans project
upcoming turn boundaries and prepare to take/yield the floor *before* the current turn ends;
agents that wait for a full silence feel sluggish and interrupt-prone. Turn-taking is Gabriel
Skantze's central research area, so this capability speaks directly to a key panelist.

**retico source.** `retico-maai`'s `TurnTakingModule` runs **Voice Activity Projection (VAP)** —
a model that continuously predicts the near-future voice activity of both parties from audio,
yielding a probability of an imminent turn shift. Subscribed directly to the microphone (parallel
to ASR), so its output leads the transcript. Emitted as `turn.state` (`state`, `p_shift`,
`p_user`).

**Vizij rendering.** Posture, not an impulse:
- `user_speaking` → **mutual gaze** at the user + idle micro-saccades ("I'm attending to you").
- `user_yielding` (rising `p_shift`) → slight **brow raise / lean** ("I'm getting ready").
- `agent_should_speak` → **blink** + hold gaze as the agent takes the floor.
Rendered via `gazePosture` on `gaze.eyes` + `brow.raise`, smoothed 0.3–0.4 s. Claims the `turn`
gaze slot (below aversion/joint-attention).

## 7.2 Backchanneling

**HRI grounding.** Listeners emit continuers ("mm-hm", "yeah", brief nods) to signal understanding
without taking the floor. Well-timed backchannels make a listener feel present; absent or
mistimed ones make an agent feel dead or interrupting. Backchannel timing is a classic
incremental-dialogue result and is not something turn-based stacks can do.

**retico source.** `retico-maai`'s `BackchannelModule` predicts *moments* appropriate for a
listener response, emitted as `backchannel.cue` (`kind`, `intensity`).

**Vizij rendering.** A brief **impulse**: head-pitch dip + brow flash (+ optional small `jaw.open`
"mm"), 0.12–0.2 s, amplitude scaled by `intensity`. Uses `gaze.head` as an impulse that *rides on
top of* the current gaze posture (does not steal the gaze slot), so the agent can backchannel
while maintaining mutual gaze. Handler `impulseNodBrow`.

## 7.3 Nodding

**HRI grounding.** Nods are a distinct listener signal (agreement / grounding) with their own
timing, often at clause boundaries. Treated separately from backchannels because the prediction
model and the motion (a clean head oscillation) differ.

**retico source.** `retico-maai`'s `NodPredictionModule`, emitted as `nod.cue` (`amplitude`,
`count`).

**Vizij rendering.** A scripted **head-pitch oscillation** of `count` cycles (~0.18 s down-up
each), angle scaled by `amplitude`. Handler `nodSequence` on `gaze.head`. Like backchannels, it
rides on top of gaze posture.

## 7.4 Lip-sync (visemes)

**HRI grounding.** Mouth motion matched to speech is the most immediately legible sign of a
"speaking" agent; desync is uncanny. This is the gap retico does not fill (its TTS emits audio,
not phoneme timing), so it is where the bridge adds a concrete piece.

**retico source.** The TTS module emits an audio IU + the spoken text (`speech.audio`), and an
end/commit (`speech.end`). No phoneme timing from retico.

**Vizij rendering.** Client-side by default (Option A): the reused `useVisemeMouth` + `phoneme-core`
derive per-frame viseme pose weights from the audio (+text) and drive `pose.viseme.*` channels
(60 ms/frame, ~20 ms lead). Option B (Polly viseme marks) is a fidelity upgrade. `speech.end`
zeroes residual visemes. See [06 §6.4](06-vizij-frontend.md#64-lip-sync--two-viable-paths).

## 7.5 Emotion

Two distinct sub-capabilities, deliberately separated:

### 7.5a User emotion → empathic mirror (`emotion.fer`)
**HRI grounding.** Reading and (appropriately) mirroring a partner's affect supports rapport and
grounding. **retico source:** `retico-vision` + an FER model over the webcam, emitted as
`emotion.fer` (`emotion`, `confidence`, `dist`). **Vizij rendering:** `poses/{emotion}.weight =
confidence·0.7`, slow 0.5 s tween with hysteresis (label change or Δconf > 0.2) so noise doesn't
twitch the face. Handler `emotionMirror`.

### 7.5b Agent emotion → expressive speech (`emotion.affect`)
**HRI grounding.** The agent's own face should carry the affect of what it is saying (concern,
warmth). **retico source:** an affect tag from the LLM (prompted to emit one) and/or TTS prosody,
emitted as `emotion.affect` (`emotion`, `intensity`, `lengthSeconds`). **Vizij rendering:**
attack (0.25 s) → hold → decay to neutral over `lengthSeconds`. Handler `emotionAffect` (reuse
`useAgentFaceTools.applyEmotion`).

Both use the canonical emotion set (`neutral|happy|sad|angry|surprise|concerned|sleepy`); FER label
sets are folded to it in the bridge.

## 7.6 Gaze

**HRI grounding.** Gaze does enormous conversational work: **mutual gaze** signals attention,
**aversion** accompanies turn-planning ("thinking"), and **joint attention** coordinates reference
to a shared object/space. Gaze is core to naturalistic HRI and a strong multimodality story.

**retico source.** Gaze is *derived by the bridge* rather than a single module output — from turn
state, an "LLM pending / thinking" flag, and (optionally) vision targets. Emitted as `gaze.intent`
(`mode ∈ mutual|aversion|joint_attention|idle`, `x`, `y`, `holdSeconds`).

**Vizij rendering.** `gazeTarget` on `gaze.eyes` (+ `gaze.head` for joint attention), 0.2–0.3 s,
with an auto-return timer for aversion. Subject to the gaze arbiter
(`joint_attention > aversion > turn > idle`). Reuses `useAgentFaceTools.applyGaze` (cross-eye L/R
split). Idle micro-saccades + blink fill the floor.

## 7.7 How the capabilities compose

- **Gaze** channels are arbitrated (one posture/target at a time).
- **Nod / backchannel** head impulses ride on top of gaze without stealing it.
- **Emotion** pose weights compose with everything (capped at 0.7 so blends don't over-drive).
- **Visemes** own the mouth poses during speech; emotion still colors brow/eyes.

The result is that, e.g., during "The Listener," the face can hold mutual gaze (gaze slot = turn
posture), nod at a clause boundary (head impulse), flash a brow backchannel (brow impulse), and
carry a faint mirrored smile (emotion pose) — four capabilities on one face without conflict. That
coherence *is* the contribution, and the arbitration policy that achieves it is the editable
mapping ([04](04-iu-animation-mapping.md)).

## 7.8 How head motion is actually implemented (rig constraint)

Head nods/shakes/tilts are applied as a **CSS transform on the element wrapping the face
canvas**, not through the rig. This is worth stating plainly because the obvious
assumption ("the rig has no head") is wrong, and so is the next one ("then just drive
it").

The GLB *does* have a whole-head transform node — `Face_Tran_Rot_C`, the parent of every
face part — and the rig graph exposes `/propsrig/face_tran_rot_c/{rotation,translation,
scale}/{x,y,z}`. But those semantic paths are **computed** nodes (a `clamp` fed by
`baseline + override`), not writable inputs. The writable inputs are
`rig/<faceId>/override/propsrig_face_tran_rot_c_<channel>/{enabled,value}`, and the
current `@vizij/runtime-react` build surfaces **none** of the 452 `override/*` paths in
`inputConstraints` (0 of 1356 listed inputs), nor does `resolveFaceControls` expose a
head control (it covers eyes, eyelids, blink only). Writing the computed path appears to
work until the rig graph next re-evaluates, then snaps back — which makes it useless for
sustained motion.

So: compositing-layer head motion is a deliberate, documented workaround, and it is
honest to describe it as such. The rig-native path opens up if vizij-web either exposes
the `override/*` inputs or ships a head pose in the rig bundle; the mapping in
`frontend/src/drivers/reticoMapping.ts` is structured so only `HEAD` and `applyHead`
would change.

## 7.9 How affect is determined (and why it's an IU)

retico-core defines no emotion or affect IU — the inventory is `AudioIU`, `TextIU`,
`SpeechRecognitionIU`, `GeneratedTextIU`, `DialogueActIU`, `EndOfTurnIU`, `SpeechIU`,
`RobotStateIU`, `GenericDictIU` and friends. The framework's convention is that you
**define your own IU subclass and produce it from a module**, which is exactly what
retico-maai does: `MaaiIU(GenericDictIU)` → `VAPIU` / `BackchannelIU` / `NodIU`.

So we define `AffectIU(GenericDictIU)` carrying
`{emotion, intensity, source}`, produced by `AffectModule` (reply text in, affect out)
and consumed by the WebSocket bridge, which classifies it into an `emotion.affect` event.

This is deliberately *not* a direct broadcast from the LLM module, which is what it was
first. Keeping affect in the IU graph means:

- it can be **revised** — ADD a keyword guess now, REVOKE and re-ADD when the model's own
  tag or (later) facial-expression recognition of the *user* provides better evidence;
- anything downstream can **subscribe** to it, not just the browser bridge — a robot
  driver via `retico-rosbridge` would get affect for free;
- it is **grounded**: each `AffectIU` points at the `GeneratedTextIU` it came from, so
  provenance survives into the event stream.

Two sources feed it, in order of preference:

1. **The model declares it.** The system prompt asks for a leading tag —
   `[happy] Good morning!` — which is stripped before the text reaches TTS. Putting the
   tag *first* matters: with streaming, the face must be set as the first clause is
   spoken, not after the reply completes.
2. **Keyword inference** over the reply text, when the model ignores the instruction.
   This is not a vestigial fallback — small local models skip the tag often. In testing,
   qwen3-1.7b tagged "I just got wonderful news!" as `excited` but produced no tag for
   "My cat died yesterday", which the fallback correctly read as `sad`.

The honest limitation: this is the agent's *intended* affect, declared by the thing
generating the words. It is not a perception of the user's emotion — that needs the
camera path (`retico-vision`), which is why `emotion.fer` is defined in the protocol but
never emitted.

## 7.10 Known gaps / honesty for the paper

- **Nod/backchannel timing quality** depends entirely on MaAI's predictors; we render them, we do
  not improve them. Frame accordingly.
- **FER is noisy**; hysteresis hides jitter but the mirror is coarse (categorical, not dimensional).
- **Joint attention** needs a real target source; the MVP may script it in the Empathic Mirror
  vignette and mark it as such rather than claim robust gaze-following.
- **Client-side viseme alignment** is heuristic in baseline mode; Polly (Option B) is the honest
  path to tight sync if reviewers push on lip-sync fidelity.
