// The editable IU→face mapping (docs/04). Data, not logic: tweak targets/timings
// here without touching VizijReticoDriver.
//
// Channel names are resolved from the live rig's inputConstraints (see
// resolveChannels) so the mapping stays rig-agnostic. This Quori face exposes
// /gaze/{left_right,up_down}, /lids/blink, /brow/*, /mouth/* — but NO head-pitch
// channel, so nods/backchannels are rendered with the eyes/brow instead of a head
// nod (see docs/07 §7.8).

export type Vec2 = { x: number; y: number };

// Normalized gaze targets (-1..1; (0,0) = looking at the camera). Values chosen for
// clear, legible contrast between conversational states (tunable).
export const GAZE = {
  camera: { x: 0, y: 0 } as Vec2, // engaged: looking right at the partner
  idle: { x: 0.55, y: -0.45 } as Vec2, // disengaged: glance away/down in silence
  aversion: { x: -0.5, y: 0.55 } as Vec2, // "thinking": look up and away
};

export interface TurnPosture {
  gaze: Vec2;
  browRaise: number; // 0..1 fraction applied to vertical brow channels
  blink?: boolean;
  durationMs: number;
  // transient: glance to `gaze` briefly, then ease back to the resting (camera) gaze,
  // instead of holding the posture. Prevents getting "stuck" looking away.
  transient?: boolean;
}

// turn.state → attentive posture. Editable. The resting gaze is the camera (engaged);
// only agent_should_speak looks away, and only as a brief "thinking" glance.
export const TURN_POSTURE: Record<string, TurnPosture> = {
  user_speaking: { gaze: GAZE.camera, browRaise: 0.15, durationMs: 350 }, // lean in, attentive
  user_yielding: { gaze: GAZE.camera, browRaise: 0.6, durationMs: 250 }, // anticipatory brow raise
  agent_should_speak: { gaze: GAZE.aversion, browRaise: 0.3, blink: true, durationMs: 250, transient: true }, // brief glance away to "think", then back
  agent_speaking: { gaze: GAZE.camera, browRaise: 0.1, durationMs: 300 },
  mutual_silence: { gaze: GAZE.camera, browRaise: 0.0, durationMs: 700 }, // idle: keep looking at the user
};

// backchannel.cue → quick brow flash (no head channel on this rig).
export const BACKCHANNEL = { browRaise: 0.8, upMs: 110, downMs: 240 };

// Blinking. Cue-driven blinks (turn transitions, backchannels) are sparse by design, and
// the rig's built-in idle animation is switched off so it can't fight the driver — so
// without a spontaneous blink the face just stares. Humans blink every ~2–8 s; the
// jittered interval keeps it from looking metronomic.
export const BLINK = {
  closeMs: 80,
  openMs: 120,
  holdMs: 90,
  /** Ignore a new blink this soon after the last one (stops cue bursts flickering). */
  minGapMs: 900,
  idleMinMs: 2800,
  idleMaxMs: 6500,
};

// nod.cue → head motion, applied as a CSS transform on the element wrapping the face
// canvas rather than through the rig.
//
// Why not the rig: the GLB *does* have a whole-head transform node (`Face_Tran_Rot_C`,
// the parent of every face part) and the rig graph exposes it, but only as a *computed*
// value — `/propsrig/face_tran_rot_c/rotation/x` is a clamp node fed by
// baseline + override. The writable inputs are
// `rig/<faceId>/override/propsrig_face_tran_rot_c_rotation_x/{enabled,value}`, and this
// runtime build does not surface any `override/*` path in `inputConstraints`
// (0 of 1356), nor does `resolveFaceControls` expose a head control. Writing the
// computed path appears to work only until the graph re-evaluates, then snaps back.
// So head motion lives at the compositing layer until vizij-web exposes the override
// inputs (or a head pose is authored into the rig bundle). See docs/07.
export const HEAD = {
  /** Nod: drop + pitch forward, repeated. */
  nod: { pitchDeg: 8, dropPx: 16, halfPeriodMs: 170 },
  /** Shake: yaw side to side — a "no" gesture. */
  shake: { yawDeg: 9, halfPeriodMs: 150, cycles: 2 },
  /** Tilt: roll, held while a quizzical emotion is active. */
  tilt: { rollDeg: 6, ms: 450 },
  restMs: 280,
  perspectivePx: 1400,
};

// nod.cue → small eye "dip" layered under the head nod as an accent.
export const NOD = { dip: 0.22, perCycleMs: 190 };

// The rig's base emotion poses (verified on quori_latest: each blends brow+eye+mouth
// into a legible expression, so we drive these rather than the subtle individual
// brow/mouth channels). These are the primitives that blends are built from.
export const EMOTION_POSE: Record<string, string> = {
  happy: "/poses/pose_d_happy_d.weight",
  sad: "/poses/pose_d_sad_d.weight",
  anger: "/poses/pose_d_anger_d.weight",
  surprise: "/poses/pose_d_surprise_d.weight",
  concerned: "/poses/pose_d_concerned_d.weight",
  sleepy: "/poses/pose_d_sleepy_d.weight",
};

// emotion.affect / emotion.fer → a *blend* of base pose weights (0..1 each). Because the
// poses are additive, emotions the rig has no dedicated pose for are expressed as
// mixtures (e.g. fear ≈ surprise + concern). intensity scales the whole blend; the driver
// zeroes every pose not in the active blend. "neutral" (or unknown) = {} = all → 0.
export type EmotionBlend = Partial<Record<keyof typeof EMOTION_POSE, number>>;
export const EMOTION_BLEND: Record<string, EmotionBlend> = {
  // base emotions (identity blends)
  happy: { happy: 1.0 },
  sad: { sad: 1.0 },
  anger: { anger: 1.0 },
  surprise: { surprise: 1.0 },
  concerned: { concerned: 1.0 },
  sleepy: { sleepy: 1.0 },
  neutral: {},
  // derived blends
  fear: { surprise: 0.6, concerned: 0.5 },
  excited: { happy: 0.8, surprise: 0.5 },
  disgust: { concerned: 0.7, anger: 0.4 },
  confused: { concerned: 0.6, surprise: 0.35 },
  content: { happy: 0.45 },
  bored: { sleepy: 0.6, sad: 0.2 },
};
// Map common synonyms (e.g. from a FER model) onto a key in EMOTION_BLEND.
export const EMOTION_ALIASES: Record<string, string> = {
  joy: "happy",
  angry: "anger",
  fearful: "fear",
  scared: "fear",
  surprised: "surprise",
  worried: "concerned",
  tired: "sleepy",
  disgusted: "disgust",
};
export const EMOTION = { holdAfterSpeechMs: 1200, fadeMs: 500 };

// speech.audio → mouth. Two modes, chosen by whether the event carries speech marks:
//
// 1. Visemes (AWS Polly): phoneme-timed marks drive the rig's viseme poses — real mouth
//    shapes, in sync with the audio.
// 2. Amplitude (gTTS and anything else without marks): jaw_open follows playback RMS.
//    The mouth opens and closes but never forms shapes; it's the honest fallback.
export const LIPSYNC = {
  channel: "/standard/vizij/mouth/morph/jaw_open",
  gain: 3.5,
  max: 1.0,
  smoothing: 0.5, // 0..1 low-pass toward the new amplitude each frame
  /** Cross-fade between viseme poses. Short — phonemes are ~60-120 ms apart. */
  visemeFadeMs: 55,
  /** A little jaw under the visemes stops the mouth reading as flat. */
  visemeJaw: 0.25,
};

// Polly viseme code -> this rig's viseme pose id. Mirrors POLLY_TO_FACE_SEGMENT in
// @vizij/speech-react (kept here rather than taking the dependency, so the mapping is
// editable alongside the rest of the IU->animation config). "sil" = mouth closed.
export const POLLY_VISEME_POSE: Record<string, string> = {
  p: "pose_p",
  t: "pose_t",
  T: "pose_t_2",
  s: "pose_s",
  S: "pose_s",
  f: "pose_f",
  k: "pose_k",
  i: "pose_i",
  r: "pose_r",
  l: "pose_r",
  u: "pose_u",
  a: "pose_a",
  e: "pose_e_2",
  E: "pose_e",
  o: "pose_o",
  O: "pose_o_2",
  "@": "pose_pzzzfnvy",
};

export const visemePosePath = (poseId: string) => `/poses/${poseId}.weight`;

export interface FaceChannels {
  gazeX?: string;
  gazeY?: string;
  blink?: string;
  brow: string[];
  mouthOpen?: string;
}

/** Resolve semantic channels against the rig's actual input paths. */
export function resolveChannels(inputPaths: string[]): FaceChannels {
  const set = new Set(inputPaths);
  const has = (k: string) => (set.has(k) ? k : undefined);
  const first = (...ks: string[]) => ks.find((k) => set.has(k));
  return {
    gazeX: has("/gaze/left_right"),
    gazeY: has("/gaze/up_down"),
    blink: has("/lids/blink"),
    // vertical brow channels (raise/lower)
    brow: inputPaths.filter((k) => /^\/brow\/.*(midud|outud|inud)\/value$/.test(k)),
    // Jaw-open for amplitude lip-sync. NOTE: on the current face.glb + published
    // runtime-react@0.1.0, mouth inputs don't visibly deform the mesh (its embedded
    // mouth animations fail to register — "missing field id"); expected to work on
    // the newer vizij packages. The rig also exposes viseme poses (/poses/pose_{a,e,
    // i,o,u,...}) for higher-fidelity lip-sync later.
    mouthOpen: first(
      "/standard/vizij/mouth/morph/jaw_open",
      "/propsrig/mouth/jawud/value",
      "/mouth/chin",
    ),
  };
}
