import { useEffect, useState, type MutableRefObject } from "react";
import type { ReticoEvent } from "../net/wsClient";
import { describeEvent } from "./ExplainPanel";

export type PipelineInfo = {
  mode?: string;
  capture?: string;
  turn_taking?: string;
  backchannel?: boolean;
  nod?: boolean;
  asr?: string;
  llm?: { model?: string; gated_on_turn?: boolean };
  tts?: string;
  lipsync?: string;
} | null;

export type DialogueState = { state: string; text: string } | null;

type Stage = {
  key: string;
  icon: string;
  name: string;
  wired: string | null; // what's wired here (null = not wired / n/a)
  activeTypes: string[]; // event types (or virtual keys) whose recency lights this stage
  value: () => string;
};

const RECENT_MS = 1600;

export function PipelinePanel({
  pipeline,
  mode,
  listening,
  partial,
  log,
  dialogue,
  activityRef,
}: {
  pipeline: PipelineInfo;
  mode: string | null;
  listening: boolean;
  partial: string;
  log: ReticoEvent[];
  dialogue: DialogueState;
  activityRef: MutableRefObject<Record<string, number>>;
}) {
  // Re-render on a timer so the "active" glow fades as events go stale.
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => (t + 1) % 1_000_000), 220);
    return () => window.clearInterval(id);
  }, []);

  const now = Date.now();
  const seen = (type: string, within = RECENT_MS) => now - (activityRef.current[type] ?? 0) < within;
  const turn = log.find((e) => e.type === "turn.state");
  const heard = log.find((e) => e.type === "asr.text");
  const speaking = seen("speech.audio", 4000) && !seen("speech.end", 500);

  const maai = mode === "maai";
  const p = pipeline ?? {};

  const stages: Stage[] = [
    {
      key: "capture",
      icon: "🎤",
      name: "Mic capture",
      wired: p.capture ?? "browser mic",
      activeTypes: ["mic"],
      value: () => (listening ? "capturing…" : "off — press ‘listen’"),
    },
    {
      key: "stream",
      icon: "↕",
      name: "Audio → backend",
      wired: "WebSocket · 10 ms frames",
      activeTypes: ["mic"],
      value: () => (listening ? "streaming PCM" : "idle"),
    },
    {
      key: "turn",
      icon: "🔄",
      name: "Turn-taking (VAP)",
      wired: maai ? p.turn_taking ?? "retico-maai" : "synthetic",
      activeTypes: ["turn.state"],
      value: () =>
        turn
          ? `${turn.payload.state} · shift ${Number(turn.payload.p_shift ?? 0).toFixed(2)}`
          : "—",
    },
    {
      key: "backchannel",
      icon: "👂",
      name: "Backchannel",
      wired: maai && p.backchannel ? "on" : null,
      activeTypes: ["backchannel.cue"],
      value: () => (seen("backchannel.cue") ? "cue → blink" : "listening"),
    },
    {
      key: "nod",
      icon: "🙂",
      name: "Nod",
      wired: maai && p.nod ? "on" : null,
      activeTypes: ["nod.cue"],
      value: () => (seen("nod.cue") ? "cue → eye-dip" : "listening"),
    },
    {
      key: "asr",
      icon: "📝",
      name: `ASR (${p.asr ?? (maai ? "?" : "n/a")})`,
      wired: maai ? p.asr ?? null : null,
      activeTypes: ["asr.text", "asr.partial"],
      value: () =>
        partial
          ? `“${partial}” …`
          : heard
            ? `“${heard.payload.text}”${heard.payload.final ? " (final)" : " …"}`
            : "—",
    },
    {
      key: "llm",
      icon: "🧠",
      name: "LLM dialogue",
      wired: maai ? `${p.llm?.model ?? "?"}${p.llm?.gated_on_turn ? " · gated" : ""}` : null,
      activeTypes: ["dialogue.state"],
      value: () => {
        if (!dialogue) return "idle";
        if (dialogue.state === "waiting_for_turn") return "⏳ waiting for the floor…";
        if (dialogue.state === "thinking") return "💭 thinking…";
        if (dialogue.state === "spoke") return `→ “${dialogue.text}”`;
        return dialogue.state;
      },
    },
    {
      key: "tts",
      icon: "🔊",
      name: "TTS",
      wired: maai ? p.tts ?? "gTTS" : "gTTS",
      activeTypes: ["speech.audio"],
      value: () => (speaking ? "speaking…" : "idle"),
    },
    {
      key: "face",
      icon: "😐",
      name: "Face driver",
      wired: p.lipsync ?? "gaze · blink · emotion · jaw",
      activeTypes: ["turn.state", "emotion.affect", "speech.audio", "nod.cue", "backchannel.cue"],
      value: () => {
        const emo = log.find((e) => e.type === "emotion.affect");
        const parts = [];
        if (turn) parts.push(turn.payload.state);
        if (emo && seen("emotion.affect", 6000)) parts.push(`emotion:${emo.payload.emotion}`);
        if (speaking) parts.push("lip-sync");
        return parts.length ? parts.join(" · ") : "resting";
      },
    },
  ];

  const dot = (stage: Stage) => {
    if (stage.wired === null) return "bg-neutral-700"; // not wired
    const active = stage.activeTypes.some((t) => (t === "mic" ? listening : seen(t)));
    return active ? "bg-emerald-400 shadow-[0_0_8px_2px_rgba(52,211,153,0.6)]" : "bg-neutral-500";
  };

  return (
    <div className="absolute bottom-3 left-3 flex max-h-[80vh] w-[33rem] max-w-[48vw] flex-col rounded bg-neutral-950/85 p-3 text-xs text-neutral-100 backdrop-blur">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-semibold">pipeline · what’s happening &amp; what’s active</span>
        <span
          className={`rounded px-2 py-0.5 ${maai ? "bg-emerald-900/60" : "bg-amber-900/50"}`}
        >
          {mode ?? "…"}
        </span>
      </div>

      <div className="flex flex-col">
        {stages.map((s, i) => (
          <div key={s.key}>
            <div className={`flex items-center gap-2 ${s.wired === null ? "opacity-40" : ""}`}>
              <span className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${dot(s)}`} />
              <span className="w-5 shrink-0 text-center">{s.icon}</span>
              <span className="w-36 shrink-0">
                <span className="font-medium">{s.name}</span>
                <span className="block text-[10px] leading-tight text-neutral-400">
                  {s.wired === null ? "not wired" : s.wired}
                </span>
              </span>
              <span className="flex-1 truncate text-neutral-200" title={s.value()}>
                {s.value()}
              </span>
            </div>
            {i < stages.length - 1 && (
              <div className="ml-[4px] h-2 w-px bg-neutral-700" aria-hidden />
            )}
          </div>
        ))}
      </div>

      <div className="mb-1 mt-3 opacity-60">recent events (newest first)</div>
      <div className="flex max-h-28 flex-col gap-0.5 overflow-auto">
        {log.slice(0, 10).map((e) => {
          const d = describeEvent(e);
          return (
            <div key={e.seq} className="flex gap-2">
              <span className="w-10 shrink-0 tabular-nums opacity-40">#{e.seq}</span>
              <span className="flex-1 truncate" title={`${d.title} — ${d.detail}`}>
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
