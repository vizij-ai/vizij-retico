import { useEffect, useState, type MutableRefObject } from "react";
import type { ReticoEvent } from "../net/wsClient";
import { describeEvent } from "./ExplainPanel";

export type ProviderOption = {
  id: string;
  label: string;
  note?: string;
  requires_key?: boolean;
  available?: boolean;
};
export type ProviderRegistry = Record<
  string,
  { active?: string | null; options: ProviderOption[] }
>;

export type PipelineInfo = {
  mode?: string;
  capture?: string;
  turn_taking?: string;
  backchannel?: boolean;
  nod?: boolean;
  asr_options?: string[];
  llm?: { model?: string; gated_on_turn?: boolean };
  tts?: string;
  lipsync?: string;
  providers?: ProviderRegistry;
} | null;

export type DialogueState = { state: string; text: string } | null;

type Row = {
  key: string;
  depth: number; // 0 = trunk, 1 = branch, 2+ = sub-branch
  icon: string;
  name: string;
  wired: string | null; // null => not wired / n/a (rendered dimmed)
  note?: string; // clarifies what actually flows along this edge
  activeKeys: string[]; // event types (or "mic") whose recency lights this row
  value: string;
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
  asrSource,
  activeProviders = {},
}: {
  pipeline: PipelineInfo;
  mode: string | null;
  listening: boolean;
  partial: string;
  log: ReticoEvent[];
  dialogue: DialogueState;
  activityRef: MutableRefObject<Record<string, number>>;
  asrSource: string | null;
  activeProviders?: Record<string, string>;
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
  const emo = log.find((e) => e.type === "emotion.affect");
  const speaking = seen("speech.audio", 4000) && !seen("speech.end", 500);
  const maai = mode === "maai";
  const p = pipeline ?? {};
  const whisper = asrSource === "whisper";

  /** Human label for whichever provider a stage is currently using. */
  const providerLabel = (kind: string): string | null => {
    const id = activeProviders[kind] ?? p.providers?.[kind]?.active;
    if (!id) return null;
    return p.providers?.[kind]?.options.find((o) => o.id === id)?.label ?? id;
  };

  const audioNote = whisper
    ? "turn-taking + Whisper ASR"
    : "turn-taking only (ASR happens in the browser)";

  const asrRow: Row = whisper
    ? {
        key: "asr",
        depth: 2, // hangs off "Audio → backend": the backend transcribes the audio
        icon: "📝",
        name: "ASR · Whisper",
        wired: "retico-whisperasr (local)",
        note: "transcribes the streamed audio on the backend",
        activeKeys: ["asr.text"],
        value: heard ? `“${heard.payload.text}”${heard.payload.final ? " (final)" : " …"}` : "—",
      }
    : {
        key: "asr",
        depth: 1, // a sibling branch off the mic: text goes straight over the WS
        icon: "📝",
        name: "ASR · Browser",
        wired: "Web Speech API (Chrome)",
        note: "text sent straight to the backend — the audio stream is not used for ASR",
        activeKeys: ["asr.text", "asr.partial"],
        value: partial
          ? `“${partial}” …`
          : heard
            ? `“${heard.payload.text}”${heard.payload.final ? " (final)" : " …"}`
            : "—",
      };

  // Only stages that actually apply to the current settings are listed — a stage that
  // isn't wired in this configuration is omitted rather than shown greyed out.
  const rows: Row[] = [];

  if (maai) {
    rows.push({
      key: "capture",
      depth: 0,
      icon: "🎤",
      name: "Mic capture",
      wired: p.capture ?? "browser mic",
      activeKeys: ["mic"],
      value: listening ? "capturing…" : "off — press ‘listen’",
    });
    rows.push({
      key: "stream",
      depth: 1,
      icon: "↕",
      name: "Audio → backend",
      wired: "WebSocket · 10 ms frames",
      note: audioNote,
      activeKeys: ["mic"],
      value: listening ? "streaming PCM" : "idle",
    });
  }

  rows.push({
    key: "turn",
    depth: maai ? 2 : 0,
    icon: "🔄",
    name: "Turn-taking (VAP)",
    wired: maai ? p.turn_taking ?? "retico-maai" : "synthetic (FakeTurnModule)",
    activeKeys: ["turn.state"],
    value: turn
      ? `${turn.payload.state} · shift ${Number(turn.payload.p_shift ?? 0).toFixed(2)}`
      : "—",
  });

  if (maai && p.backchannel) {
    rows.push({
      key: "backchannel",
      depth: 3,
      icon: "👂",
      name: "Backchannel",
      wired: "on",
      activeKeys: ["backchannel.cue"],
      value: seen("backchannel.cue") ? "cue → blink" : "listening",
    });
  }
  if (maai && p.nod) {
    rows.push({
      key: "nod",
      depth: 3,
      icon: "🙂",
      name: "Nod",
      wired: "on",
      activeKeys: ["nod.cue"],
      value: seen("nod.cue") ? "cue → eye-dip" : "listening",
    });
  }

  if (maai) {
    // whisper: depth 2 (under Audio → backend). browser: depth 1 (its own branch).
    rows.push(asrRow);
    rows.push({
      key: "llm",
      depth: 0,
      icon: "🧠",
      name: "LLM dialogue",
      wired: `${providerLabel("llm") ?? p.llm?.model ?? "?"}${
        p.llm?.gated_on_turn ? " · gated on turn" : ""
      }`,
      note: "receives the transcript, whichever ASR produced it",
      activeKeys: ["dialogue.state"],
      value: !dialogue
        ? "idle"
        : dialogue.state === "waiting_for_turn"
          ? "⏳ waiting for the floor…"
          : dialogue.state === "thinking"
            ? "💭 thinking…"
            : dialogue.state === "spoke"
              ? `→ “${dialogue.text}”`
              : dialogue.state,
    });
  }

  rows.push({
    key: "tts",
    depth: 0,
    icon: "🔊",
    name: "TTS",
    wired: providerLabel("tts") ?? p.tts ?? "gTTS",
    activeKeys: ["speech.audio"],
    value: speaking ? "speaking…" : "idle",
  });
  rows.push({
    key: "face",
    depth: 0,
    icon: "😐",
    name: "Face driver",
    wired: p.lipsync ?? "gaze · blink · emotion · jaw",
    activeKeys: ["turn.state", "emotion.affect", "speech.audio", "nod.cue", "backchannel.cue"],
    value: (() => {
      const parts: string[] = [];
      if (turn) parts.push(turn.payload.state);
      if (emo && seen("emotion.affect", 6000)) parts.push(`emotion:${emo.payload.emotion}`);
      if (speaking) parts.push("lip-sync");
      return parts.length ? parts.join(" · ") : "resting";
    })(),
  });

  const dotClass = (r: Row) => {
    if (r.wired === null) return "bg-neutral-700";
    const active = r.activeKeys.some((k) => (k === "mic" ? listening : seen(k)));
    return active ? "bg-emerald-400 shadow-[0_0_8px_2px_rgba(52,211,153,0.6)]" : "bg-neutral-500";
  };

  return (
    <div className="absolute bottom-3 left-3 flex max-h-[66vh] w-[35rem] max-w-[50vw] flex-col rounded bg-neutral-950/85 p-3 text-xs text-neutral-100 backdrop-blur">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-semibold">pipeline · what’s happening &amp; what’s active</span>
        <span className={`rounded px-2 py-0.5 ${maai ? "bg-emerald-900/60" : "bg-amber-900/50"}`}>
          {mode ?? "…"}
        </span>
      </div>

      {/* What the system currently believes it heard — the headline value. */}
      <div className="mb-2 rounded bg-sky-950/70 p-2">
        <span className="opacity-60">heard: </span>
        {partial ? (
          <span className="text-sky-200">“{partial}” …</span>
        ) : heard ? (
          <span className="text-sky-100">
            “{heard.payload.text}”{heard.payload.final ? "" : " …"}
          </span>
        ) : (
          <span className="opacity-50">
            {listening ? "listening…" : "nothing yet — press ‘listen’ or type a user turn"}
          </span>
        )}
      </div>

      <div className="flex flex-col overflow-auto">
        {rows.map((r) => (
          <div
            key={r.key}
            className={`flex items-start gap-2 py-[3px] ${r.wired === null ? "opacity-40" : ""}`}
            style={{ paddingLeft: `${r.depth * 14}px` }}
          >
            <span className="w-3 shrink-0 pt-[3px] text-center text-neutral-600">
              {r.depth > 0 ? "└" : ""}
            </span>
            <span className={`mt-[5px] inline-block h-2.5 w-2.5 shrink-0 rounded-full ${dotClass(r)}`} />
            <span className="w-4 shrink-0 text-center">{r.icon}</span>
            <span className="w-40 shrink-0">
              <span className="font-medium">{r.name}</span>
              <span className="block text-[10px] leading-tight text-neutral-400">
                {r.wired === null ? "not wired" : r.wired}
              </span>
              {r.note && (
                <span className="block text-[10px] italic leading-tight text-neutral-500">
                  {r.note}
                </span>
              )}
            </span>
            <span className="min-w-0 flex-1 truncate pt-[1px] text-neutral-200" title={r.value}>
              {r.value}
            </span>
          </div>
        ))}
      </div>

      <div className="mb-1 mt-2 opacity-60">recent events (newest first)</div>
      <div className="flex max-h-24 flex-col gap-0.5 overflow-auto">
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
