import { BrandMark } from "./BrandMark";
import type { WsStatus } from "../net/wsClient";

/**
 * Only what you touch during a conversation: connection state, the two capture toggles,
 * and the panel switches. Everything else moved behind those switches.
 *
 * It is a fixed-height flex row rather than the previous absolutely-positioned box, which
 * grew rightward without bound — at 1280 px the page scrolled to 1806 px and the last
 * control was unreachable.
 */

const DOT: Record<WsStatus, string> = {
  open: "bg-emerald-400",
  connecting: "bg-amber-400",
  closed: "bg-red-400",
};

function Toggle({
  on,
  onClick,
  children,
  title,
  disabled,
  tone = "neutral",
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
  disabled?: boolean;
  tone?: "neutral" | "live";
}) {
  const active = tone === "live" ? "bg-emerald-600 text-white" : "bg-neutral-700 text-neutral-100";
  return (
    <button
      className={`rounded px-2.5 py-1 text-xs transition-colors disabled:opacity-40 ${
        on ? active : "text-neutral-300 hover:bg-neutral-800"
      }`}
      onClick={onClick}
      title={title}
      disabled={disabled}
      aria-pressed={on}
    >
      {children}
    </button>
  );
}

export function TopBar({
  status,
  listening,
  onToggleListen,
  watching,
  watchLoading,
  onToggleWatch,
  wsUrl,
  settingsOpen,
  onToggleSettings,
  pipelineOpen,
  onTogglePipeline,
  devOpen,
  onToggleDev,
}: {
  status: WsStatus;
  listening: boolean;
  onToggleListen: () => void;
  watching: boolean;
  watchLoading: boolean;
  onToggleWatch: () => void;
  wsUrl: string;
  settingsOpen: boolean;
  onToggleSettings: () => void;
  pipelineOpen: boolean;
  onTogglePipeline: () => void;
  devOpen: boolean;
  onToggleDev: () => void;
}) {
  return (
    <header className="z-20 flex h-12 shrink-0 items-center gap-2 border-b border-neutral-800 bg-neutral-950 px-3">
      <BrandMark title="vizij × retico" />

      {/* Divider: identity on the left, live state and actions to its right. */}
      <span className="mx-1 h-5 w-px shrink-0 bg-neutral-800" aria-hidden />

      {/* The endpoint used to be printed in full across the bar; it is diagnostic, so it
          lives on the status dot's tooltip instead. */}
      <span
        className={`inline-block h-2 w-2 shrink-0 rounded-full ${DOT[status]}`}
        title={`websocket ${status} — ${wsUrl}`}
      />

      <Toggle on={listening} onClick={onToggleListen} tone="live" title="Stream the microphone">
        {listening ? "● listening" : "listen"}
      </Toggle>
      <Toggle
        on={watching}
        onClick={onToggleWatch}
        tone="live"
        disabled={watchLoading}
        title="Camera → MediaPipe blendshapes. Only the coefficients are sent; no video leaves the browser."
      >
        {watchLoading ? "loading…" : watching ? "● watching" : "watch me"}
      </Toggle>

      <div className="flex-1" />

      <Toggle on={settingsOpen} onClick={onToggleSettings} title="Providers and voices">
        settings
      </Toggle>
      <Toggle on={pipelineOpen} onClick={onTogglePipeline} title="What each stage is doing">
        pipeline
      </Toggle>
      <Toggle on={devOpen} onClick={onToggleDev} title="Debug tools and sliders">
        dev
      </Toggle>
    </header>
  );
}
