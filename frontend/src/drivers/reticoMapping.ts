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
}

// turn.state → attentive posture. Editable.
export const TURN_POSTURE: Record<string, TurnPosture> = {
  user_speaking: { gaze: GAZE.camera, browRaise: 0.15, durationMs: 350 }, // lean in, attentive
  user_yielding: { gaze: GAZE.camera, browRaise: 0.6, durationMs: 250 }, // anticipatory brow raise
  agent_should_speak: { gaze: GAZE.aversion, browRaise: 0.3, blink: true, durationMs: 250 }, // glance away to "think"
  agent_speaking: { gaze: GAZE.camera, browRaise: 0.1, durationMs: 300 },
  mutual_silence: { gaze: GAZE.idle, browRaise: 0.0, durationMs: 600 }, // disengage
};

// backchannel.cue → quick brow flash (no head channel on this rig).
export const BACKCHANNEL = { browRaise: 0.8, upMs: 110, downMs: 240 };

// nod.cue → eye "dip" surrogate (down then back) per cycle, since there's no head.
export const NOD = { dip: 0.5, perCycleMs: 190 };

export interface FaceChannels {
  gazeX?: string;
  gazeY?: string;
  blink?: string;
  brow: string[];
}

/** Resolve semantic channels against the rig's actual input paths. */
export function resolveChannels(inputPaths: string[]): FaceChannels {
  const set = new Set(inputPaths);
  const has = (k: string) => (set.has(k) ? k : undefined);
  return {
    gazeX: has("/gaze/left_right"),
    gazeY: has("/gaze/up_down"),
    blink: has("/lids/blink"),
    // vertical brow channels (raise/lower)
    brow: inputPaths.filter((k) => /^\/brow\/.*(midud|outud|inud)\/value$/.test(k)),
  };
}
