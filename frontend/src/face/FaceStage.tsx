import { useEffect, useRef, useState } from "react";
import {
  VizijRuntimeProvider,
  VizijRuntimeFace,
  useVizijRuntime,
  resolveFaceControls,
  type VizijAssetBundle,
} from "@vizij/runtime-react";
import { WsClient, type ReticoEvent, type WsStatus } from "../net/wsClient";
import { createReticoDriver } from "../drivers/VizijReticoDriver";
import { useMicCapture } from "../capture/useMicCapture";
import { useBrowserSpeech } from "../capture/useBrowserSpeech";
import { DevControls } from "./devControls";
import { PipelinePanel, type PipelineInfo, type DialogueState } from "./PipelinePanel";

// Our own GLB, hosted under frontend/public/assets/.
const GLB_URL = `${import.meta.env.BASE_URL}assets/face.glb`;
const WS_URL = `ws://${location.hostname}:8770/ws`;

const assetBundle: VizijAssetBundle = {
  namespace: "vizij-retico",
  glb: { kind: "url", src: GLB_URL, aggressiveImport: true },
  pose: { stageNeutralFilter: (_id, path) => !path.includes("/color/") },
};

/** Registers the retico input driver and owns the WebSocket connection. */
function ReticoBridge({
  headRef,
  showPanel,
}: {
  headRef: React.RefObject<HTMLDivElement | null>;
  showPanel: boolean;
}) {
  const rt = useVizijRuntime();
  const [status, setStatus] = useState<WsStatus>("connecting");
  const [last, setLast] = useState<ReticoEvent | null>(null);
  const [log, setLog] = useState<ReticoEvent[]>([]);
  const [mode, setMode] = useState<string | null>(null);
  const [asrSource, setAsrSource] = useState<string | null>(null);
  const [pipeline, setPipeline] = useState<PipelineInfo>(null);
  const [dialogue, setDialogue] = useState<DialogueState>(null);
  const [asrLoading, setAsrLoading] = useState(false);
  const [asrNotice, setAsrNotice] = useState<string | null>(null);
  const activityRef = useRef<Record<string, number>>({});
  const rtRef = useRef(rt);
  rtRef.current = rt;
  const startedRef = useRef(false);
  const wsRef = useRef<WsClient | null>(null);
  const mic = useMicCapture(() => wsRef.current);
  const speech = useBrowserSpeech(() => wsRef.current);
  const [sayText, setSayText] = useState("Hi there! I can talk now.");
  const [userText, setUserText] = useState("");

  // Test harness: inject text as if the user spoke it, exercising the full pipeline
  // (ASR → turn gate → LLM → emotion → TTS → face) without a live mic.
  const simulateUserTurn = () => {
    const text = userText.trim();
    if (text) {
      activityRef.current["mic"] = Date.now();
      wsRef.current?.sendJSON({ type: "control", action: "simulate_user_turn", text });
    }
  };

  // One "listen" toggle: always stream audio (for turn-taking); also run browser STT
  // when the backend is in browser-ASR mode.
  const useBrowserAsr = asrSource !== "whisper";
  const listening = mic.active;
  // Only toggles the audio stream; the effect below owns starting/stopping the browser
  // recognizer (starting it here too would create a second one and duplicate results).
  const toggleListen = () => {
    if (listening) {
      mic.stop();
      speech.stop();
    } else {
      mic.start();
    }
  };

  const say = () => {
    const text = sayText.trim();
    if (text) wsRef.current?.sendJSON({ type: "control", action: "say", text });
  };

  const setAsrSourceRemote = (source: string) => {
    if (source === asrSource) return;
    if (source === "whisper") setAsrLoading(true);
    wsRef.current?.sendJSON({ type: "control", action: "set_asr_source", source });
  };

  // Browser STT only runs when the backend is consuming it; switching to Whisper hands
  // transcription to the backend, so release the recognizer's own mic capture.
  useEffect(() => {
    if (!useBrowserAsr && speech.listening) speech.stop();
    else if (useBrowserAsr && listening && !speech.listening && speech.supported) speech.start();
  }, [useBrowserAsr, listening, speech.listening, speech.supported, speech.start, speech.stop]);

  // If this browser's speech service can't work (no mic permission, offline speech
  // service, Chromium build without it), fall back to backend Whisper instead of
  // silently transcribing nothing.
  useEffect(() => {
    if (speech.fatal && useBrowserAsr) {
      setAsrNotice(
        `browser STT unavailable (${speech.fatal}) — switched to Whisper on the backend`,
      );
      setAsrSourceRemote("whisper");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speech.fatal, useBrowserAsr]);

  // Browser STT partials are frontend-only (not WS events) — mark activity so the
  // pipeline's ASR stage glows while the user is mid-utterance.
  useEffect(() => {
    if (speech.partial) activityRef.current["asr.partial"] = Date.now();
  }, [speech.partial]);

  // Connect the WebSocket once on mount, independent of the runtime lifecycle
  // (reconnect handles drops). Decoupling from `ready` avoids the socket being torn
  // down when the device recomposes during load.
  useEffect(() => {
    const ws = new WsClient(WS_URL);
    wsRef.current = ws;
    const offStatus = ws.onStatus(setStatus);
    const offEvent = ws.addEventListener((e) => {
      if ((e as { type?: string }).type === "hello") {
        const h = e as { mode?: string; asr_source?: string; pipeline?: PipelineInfo };
        setMode(h.mode ?? null);
        setAsrSource(h.asr_source ?? null);
        setPipeline(h.pipeline ?? null);
        return;
      }
      // Record client-side arrival time per event type for the pipeline "active" glow.
      activityRef.current[e.type] = Date.now();
      if (e.type === "dialogue.state") {
        setDialogue({ state: e.payload.state, text: e.payload.text ?? "" });
        return; // dialogue.state is pipeline telemetry, not a face-driving event
      }
      if (e.type === "asr.source") {
        // Whisper loads lazily on the backend; reflect loading/active/error here.
        setAsrLoading(e.payload.state === "loading");
        if (e.payload.state === "active") setAsrSource(e.payload.source ?? null);
        return;
      }
      setLast(e);
      setLog((prev) => {
        const head = prev[0];
        // collapse consecutive identical turn states to reduce noise
        if (
          e.type === "turn.state" &&
          head?.type === "turn.state" &&
          head.payload.state === e.payload.state
        ) {
          return prev;
        }
        return [e, ...prev].slice(0, 14);
      });
    });
    ws.connect();
    return () => {
      offStatus();
      offEvent();
      ws.close();
      wsRef.current = null;
    };
  }, []);

  // Stop the rig's built-in auto-playing idle animation so it doesn't blink/twitch on
  // its own and fight the driver. Re-runs when controllers register (anims can appear
  // after `ready`). Toggle back on via the dev panel's "anim" button.
  useEffect(() => {
    if (!rt.ready) return;
    rt.setAnimationActive?.(false);
    rt.controllers?.anims?.forEach((id) => rt.stopAnimation?.(id));
  }, [rt.ready, rt.controllers, rt.setAnimationActive, rt.stopAnimation]);

  // Register the driver once the runtime is ready (reading unstable-identity runtime
  // methods through a ref so this doesn't re-run and recompose the device).
  useEffect(() => {
    if (!rt.ready || !wsRef.current || startedRef.current) return;
    startedRef.current = true;
    const { registerInputDriver, animateValue, setInput, assetBundle, faceId, inputConstraints } =
      rtRef.current;
    const controls = resolveFaceControls(assetBundle, faceId, inputConstraints);
    console.log("[vizij-retico] resolved face controls", controls);
    const lifecycle = registerInputDriver(
      "retico",
      createReticoDriver(wsRef.current, controls, animateValue, {
        faceId: faceId ?? "face",
        setInput,
        headElement: () => headRef.current,
      }),
    );
    lifecycle.start(); // idempotent
    return () => {
      lifecycle.dispose();
      startedRef.current = false;
    };
  }, [rt.ready]);

  const dot = status === "open" ? "bg-emerald-400" : status === "connecting" ? "bg-amber-400" : "bg-red-400";
  return (
    <>
      {showPanel && (
        <PipelinePanel
          pipeline={pipeline}
          mode={mode}
          listening={listening}
          partial={speech.partial}
          log={log}
          dialogue={dialogue}
          activityRef={activityRef}
          asrSource={asrSource}
        />
      )}
    <div className="absolute left-3 top-3 rounded bg-neutral-950/70 px-3 py-2 text-xs text-neutral-100 backdrop-blur">
      <div className="flex items-center gap-2">
        <span className={`inline-block h-2 w-2 rounded-full ${dot}`} />
        <span>retico {status}</span>
        <span className="opacity-60">{WS_URL}</span>
        <button
          className={`ml-2 rounded px-2 py-0.5 ${listening ? "bg-emerald-600" : "bg-neutral-700"} hover:opacity-90`}
          onClick={toggleListen}
        >
          {listening ? "● listening" : "listen"}
        </button>
        <span className="ml-1 flex items-center gap-1">
          <span className="opacity-50">asr:</span>
          {(pipeline?.asr_options ?? ["browser", "whisper"]).map((opt) => (
            <button
              key={opt}
              disabled={asrLoading}
              onClick={() => setAsrSourceRemote(opt)}
              className={`rounded px-1.5 py-0.5 ${
                asrSource === opt ? "bg-emerald-600" : "bg-neutral-700 hover:bg-neutral-600"
              } ${asrLoading ? "opacity-50" : ""}`}
              title={
                opt === "browser"
                  ? "Web Speech API: transcribes in the browser, sends text (Chrome)"
                  : "retico-whisperasr: transcribes the streamed audio on the backend (local)"
              }
            >
              {opt}
            </button>
          ))}
          {asrLoading && <span className="text-amber-300">loading Whisper…</span>}
        </span>
      </div>
      {mic.error && <div className="mt-1 text-red-300">mic: {mic.error}</div>}
      {speech.error && <div className="mt-1 text-red-300">stt: {speech.error}</div>}
      {asrNotice && <div className="mt-1 text-amber-300">{asrNotice}</div>}
      {useBrowserAsr && listening && !speech.error && (
        <div className="mt-1 opacity-60">
          stt: {speech.listening ? "recognizer running" : "starting…"} · {speech.results} result
          {speech.results === 1 ? "" : "s"}
        </div>
      )}
      <div className="mt-2 flex gap-1">
        <input
          className="w-56 rounded bg-neutral-800 px-2 py-1 text-neutral-100 outline-none"
          value={sayText}
          onChange={(e) => setSayText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && say()}
          placeholder="agent says (TTS only)…"
        />
        <button className="rounded bg-teal-700 px-2 py-1 hover:bg-teal-600" onClick={say}>
          say
        </button>
      </div>
      <div className="mt-1 flex gap-1">
        <input
          className="w-56 rounded bg-neutral-800 px-2 py-1 text-neutral-100 outline-none"
          value={userText}
          onChange={(e) => setUserText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && simulateUserTurn()}
          placeholder="debug: type a user turn instead of mic…"
        />
        <button
          className="rounded bg-indigo-700 px-2 py-1 hover:bg-indigo-600"
          onClick={simulateUserTurn}
          title="Inject as a user turn: ASR → turn gate → LLM → TTS → face"
        >
          user↵
        </button>
      </div>
      {last && (
        <div className="mt-1 opacity-80">
          <span className="font-mono">{last.type}</span>{" "}
          {last.type === "turn.state" && (
            <span>
              {last.payload.state} · shift {Number(last.payload.p_shift).toFixed(2)} · user{" "}
              {Number(last.payload.p_user).toFixed(2)}
            </span>
          )}
        </div>
      )}
    </div>
    </>
  );
}

export function FaceStage() {
  const [dev, setDev] = useState(false);
  // Collapses the pipeline panel and the dev sliders for an unobstructed view of the
  // face (demos, screenshots). The connection HUD stays so `listen` is still reachable.
  const [showPanels, setShowPanels] = useState(true);
  // Wraps the face canvas so the driver can apply head motion (nod/shake/tilt) as a
  // transform — the rig's head transform isn't writable from this runtime build.
  const headRef = useRef<HTMLDivElement | null>(null);
  return (
    <VizijRuntimeProvider assetBundle={assetBundle} autostart>
      <div className="relative h-full w-full">
        <div ref={headRef} className="h-full w-full will-change-transform">
          <VizijRuntimeFace />
        </div>
        <ReticoBridge headRef={headRef} showPanel={showPanels} />
        <div className="absolute right-3 top-3 flex gap-1">
          <button
            className="rounded bg-neutral-700 px-2 py-1 text-xs text-neutral-100 hover:bg-neutral-600"
            onClick={() => setShowPanels((p) => !p)}
            title="Hide the pipeline panel and dev sliders for a clean view of the face"
          >
            {showPanels ? "hide panels" : "show panels"}
          </button>
          {showPanels && (
            <button
              className="rounded bg-neutral-700 px-2 py-1 text-xs text-neutral-100 hover:bg-neutral-600"
              onClick={() => setDev((d) => !d)}
            >
              {dev ? "hide dev" : "dev"}
            </button>
          )}
        </div>
        {showPanels && dev && <DevControls />}
      </div>
    </VizijRuntimeProvider>
  );
}
