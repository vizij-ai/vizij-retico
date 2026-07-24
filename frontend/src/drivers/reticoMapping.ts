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

// nod.cue → eye "dip" surrogate (down then back) per cycle, since there's no head.
export const NOD = { dip: 0.5, perCycleMs: 190 };

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

// speech.audio → jaw opening driven by playback amplitude. jaw_open is 0..1; gain scales
// RMS (~0..0.25) up to that range, clamped by max. Verified: jaw_open cleanly opens the
// mouth. (Phoneme viseme poses /poses/pose_{a,e,i,o,u,…}.weight exist for higher-fidelity
// lip-sync later, but need phoneme timing we don't get from gTTS.)
export const LIPSYNC = {
  channel: "/standard/vizij/mouth/morph/jaw_open",
  gain: 3.5,
  max: 1.0,
  smoothing: 0.5, // 0..1 low-pass toward the new amplitude each frame
};

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
