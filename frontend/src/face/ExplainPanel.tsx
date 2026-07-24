import type { ReticoEvent } from "../net/wsClient";
import { GAZE, TURN_POSTURE } from "../drivers/reticoMapping";

const TURN_DESC: Record<string, string> = {
  user_speaking: "User is speaking → look at them, stay engaged.",
  user_yielding: "User about to hand over the turn → hold gaze, get ready.",
  agent_should_speak: "Agent's turn → glance away to 'think', then blink.",
  agent_speaking: "Agent is speaking → look at the user.",
  mutual_silence: "Silence → disengage, glance away.",
};

function gazeWhere(g: { x: number; y: number } | undefined): string {
  if (!g) return "—";
  if (g === GAZE.camera) return "at the user (center)";
  if (g === GAZE.idle) return "away / down (disengaged)";
  if (g === GAZE.aversion) return "up & away (thinking)";
  return `(${g.x}, ${g.y})`;
}

export function describeEvent(e: ReticoEvent): { title: string; detail: string } {
  const p = e.payload ?? {};
  switch (e.type) {
    case "turn.state": {
      const posture = TURN_POSTURE[p.state];
      return {
        title: `turn.state · ${p.state}`,
        detail: `${TURN_DESC[p.state] ?? ""} → gaze ${gazeWhere(posture?.gaze)}${
          posture?.blink ? " + blink" : ""
        }  ·  p_shift ${Number(p.p_shift).toFixed(2)}, p_user ${Number(p.p_user).toFixed(2)}`,
      };
    }
    case "backchannel.cue":
      return { title: "backchannel.cue", detail: `Acknowledge with a blink (intensity ${Number(p.intensity ?? 0).toFixed(2)}).` };
    case "nod.cue":
      return { title: "nod.cue", detail: `Nod ×${p.count ?? 1} as an eye-dip (amplitude ${Number(p.amplitude ?? 0).toFixed(2)}).` };
    case "speech.audio":
      return { title: "speech.audio", detail: `Speak (play audio): “${p.text ?? ""}”` };
    case "speech.end":
      return { title: "speech.end", detail: "Utterance finished." };
    case "emotion.fer":
      return { title: "emotion.fer", detail: `User looks ${p.emotion} (${Number(p.confidence ?? 0).toFixed(2)}) → mirror it.` };
    case "emotion.affect":
      return { title: "emotion.affect", detail: `Express ${p.emotion} (${Number(p.intensity ?? 0).toFixed(2)}).` };
    case "gaze.intent":
      return { title: `gaze.intent · ${p.mode}`, detail: `Look ${p.mode} → (${p.x ?? 0}, ${p.y ?? 0}).` };
    case "asr.text":
      return {
        title: `asr.text ${p.final ? "(final)" : "(partial)"}`,
        detail: `Heard: “${p.text ?? ""}”`,
      };
    default:
      return { title: e.type, detail: JSON.stringify(p) };
  }
}

export function ExplainPanel({
  mode,
  log,
  listening = false,
  partial = "",
}: {
  mode: string | null;
  log: ReticoEvent[];
  listening?: boolean;
  partial?: string;
}) {
  const current = log.find((e) => e.type === "turn.state");
  const heard = log.find((e) => e.type === "asr.text");
  const modeNote =
    mode === "maai"
      ? "Backend: maai — driven by live mic audio (VAP model). Face should track what you say."
      : mode === "fake"
        ? "Backend: fake — SYNTHETIC turn states cycling on an ~0.8s timer (not your mic). The steady cycle is expected; run `uv run run.py maai` for real input."
        : "Backend mode unknown.";

  return (
    <div className="absolute bottom-3 left-3 w-[30rem] max-w-[46vw] rounded bg-neutral-950/80 p-3 text-xs text-neutral-100 backdrop-blur">
      <div className="mb-2 font-semibold">what the face is doing & why</div>
      <div
        className={`mb-2 rounded px-2 py-1 ${mode === "maai" ? "bg-emerald-900/60" : "bg-amber-900/50"}`}
      >
        {modeNote}
      </div>

      {partial ? (
        <div className="mb-2 rounded bg-indigo-900/50 p-2">🎙 listening: “{partial}” …</div>
      ) : (
        listening && <div className="mb-2 rounded bg-indigo-900/40 p-2 opacity-70">🎙 listening…</div>
      )}

      {heard && (
        <div className="mb-2 rounded bg-sky-900/50 p-2">
          🗣 heard: “{heard.payload.text}”{heard.payload.final ? " (final)" : " …"}
        </div>
      )}

      {current && (
        <div className="mb-2 rounded bg-neutral-800/70 p-2">
          <div className="font-mono text-teal-300">{describeEvent(current).title}</div>
          <div className="opacity-90">{describeEvent(current).detail}</div>
        </div>
      )}

      <div className="mb-1 opacity-60">recent events (newest first)</div>
      <div className="flex max-h-40 flex-col gap-1 overflow-auto">
        {log.map((e) => {
          const d = describeEvent(e);
          return (
            <div key={e.seq} className="flex gap-2">
              <span className="w-14 shrink-0 tabular-nums opacity-40">#{e.seq}</span>
              <span className="flex-1">
                <span className="font-mono text-neutral-300">{d.title}</span>
                <span className="opacity-70"> — {d.detail}</span>
              </span>
            </div>
          );
        })}
        {log.length === 0 && <div className="opacity-60">waiting for events…</div>}
      </div>
    </div>
  );
}
