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
import { useFaceExpression } from "../capture/useFaceExpression";
import { DevControls } from "./devControls";
import { PipelinePanel, type PipelineInfo, type DialogueState } from "./PipelinePanel";
import { PanelDock } from "./Panel";
import { SettingsDrawer } from "./SettingsDrawer";
import { TopBar } from "./TopBar";
import { CameraPreview } from "./CameraPreview";

// Our own GLB, hosted under frontend/public/assets/.
const GLB_URL = `${import.meta.env.BASE_URL}assets/face.glb`;
// In dev the backend is a separate process on :8770; when packaged, the same server
// serves this page, so use its origin (and wss:// behind Cloud Run's TLS).
const WS_URL =
  (import.meta.env.VITE_WS_URL as string | undefined) ??
  (import.meta.env.DEV
    ? `ws://${location.hostname}:8770/ws`
    : `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);

const assetBundle: VizijAssetBundle = {
  namespace: "vizij-retico",
  glb: { kind: "url", src: GLB_URL, aggressiveImport: true },
  pose: { stageNeutralFilter: (_id, path) => !path.includes("/color/") },
};

/** Registers the retico input driver and owns the WebSocket connection. */
function ReticoBridge({ headRef }: { headRef: React.RefObject<HTMLDivElement | null> }) {
  const rt = useVizijRuntime();
  const [status, setStatus] = useState<WsStatus>("connecting");
  const [log, setLog] = useState<ReticoEvent[]>([]);
  const [mode, setMode] = useState<string | null>(null);
  const [asrSource, setAsrSource] = useState<string | null>(null);
  const [pipeline, setPipeline] = useState<PipelineInfo>(null);
  const [dialogue, setDialogue] = useState<DialogueState>(null);
  const [asrLoading, setAsrLoading] = useState(false);
  const [asrNotice, setAsrNotice] = useState<string | null>(null);
  const [activeProviders, setActiveProviders] = useState<Record<string, string>>({});
  // Panel visibility lives here rather than in FaceStage: the controls that toggle it sit
  // in the top bar, which needs this component's connection and capture state anyway.
  const [showPanel, setShowPanel] = useState(true);
  const [dev, setDev] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Read inside the capture loop, which must not re-subscribe on every change.
  const activeProvidersRef = useRef<Record<string, string>>({});
  activeProvidersRef.current = activeProviders;
  const activityRef = useRef<Record<string, number>>({});
  const rtRef = useRef(rt);
  rtRef.current = rt;
  const startedRef = useRef(false);
  const wsRef = useRef<WsClient | null>(null);
  const mic = useMicCapture(() => wsRef.current);
  const speech = useBrowserSpeech(() => wsRef.current);
  const vision = useFaceExpression(
    () => wsRef.current,
    () => activeProvidersRef.current.fer ?? "browser",
  );
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

  // One "listen" toggle: always stream audio (turn-taking and the server-side ASRs both
  // need it); additionally run the browser recognizer only when it is the active source.
  // Allow-list rather than "not whisper": with google now an option too, a deny-list
  // would leave Web Speech running alongside a server ASR and commit two transcripts.
  const useBrowserAsr = asrSource === "browser" || asrSource === null;
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
    // Choosing the browser recognizer clears any past fatal, so the fallback effect
    // below judges this attempt rather than an old one and the choice actually sticks.
    if (source === "browser") {
      speech.clearFatal();
      setAsrNotice(null);
    }
    wsRef.current?.sendJSON({ type: "control", action: "set_asr_source", source });
  };

  // ASR keeps its own path because switching it also starts/stops the browser
  // recogniser and can involve a lazy model load; the rest are a plain control message.
  const setProvider = (kind: string, id: string) => {
    if (kind === "asr") return setAsrSourceRemote(id);
    wsRef.current?.sendJSON({ type: "control", action: "set_provider", kind, id });
  };

  // Browser STT only runs when the backend is consuming it; switching to Whisper hands
  // transcription to the backend, so release the recognizer's own mic capture.
  useEffect(() => {
    if (!useBrowserAsr && speech.listening) speech.stop();
    else if (useBrowserAsr && listening && !speech.listening && speech.supported) speech.start();
  }, [useBrowserAsr, listening, speech.listening, speech.supported, speech.start, speech.stop]);

  // If this browser's speech service can't work (no mic permission, offline speech
  // service, Chromium build without it), hand transcription to the backend instead of
  // silently transcribing nothing.
  //
  // This used to name Whisper outright. On the `lite` backend Whisper does not exist, so
  // selecting "browser" bounced straight to a source with no module behind it and the
  // app went deaf — while still reporting that it had switched. Pick from what the
  // backend says it can actually do, preferring Google STT.
  useEffect(() => {
    if (!speech.fatal || !useBrowserAsr) return;
    const options = pipeline?.providers?.asr?.options ?? [];
    const usable = (id: string) =>
      options.some((o) => o.id === id && o.available !== false);
    const fallback = ["google", "whisper"].find(usable);
    if (!fallback) {
      setAsrNotice(`browser STT unavailable (${speech.fatal}) — and no backend ASR is`);
      return;
    }
    const label = options.find((o) => o.id === fallback)?.label ?? fallback;
    setAsrNotice(`browser STT unavailable (${speech.fatal}) — switched to ${label}`);
    setAsrSourceRemote(fallback);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speech.fatal, useBrowserAsr, pipeline]);

  // Browser STT partials are frontend-only (not WS events) — mark activity so the
  // pipeline's ASR stage glows while the user is mid-utterance.
  useEffect(() => {
    if (speech.partial) activityRef.current["asr.partial"] = Date.now();
  }, [speech.partial]);

  // Blendshape frames are frontend-only until the backend answers with emotion.fer,
  // so mark activity here to light the FER stage while the camera is running.
  useEffect(() => {
    if (vision.frames) activityRef.current["fer.frames"] = Date.now();
  }, [vision.frames]);

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
        const reg = h.pipeline?.providers;
        if (reg) {
          setActiveProviders(
            Object.fromEntries(
              Object.entries(reg)
                .map(([k, v]) => [k, v.active ?? ""])
                .filter(([, v]) => v),
            ) as Record<string, string>,
          );
        }
        return;
      }
      if (e.type === "provider.state") {
        const { kind, id, state, detail, providers, active } = e.payload;
        if (state === "active") {
          // Take the whole registry when the backend sends it, not just the one kind.
          // Some kinds are derived from others — the voice list is rebuilt from the
          // active TTS, the model list from the active LLM — so patching a single key
          // leaves those dropdowns showing the *previous* provider's options. That is
          // why selecting Polly never produced Polly voices.
          if (providers) {
            setPipeline((p) => (p ? { ...p, providers } : p));
          }
          setActiveProviders((p) => ({ ...p, ...(active ?? {}), [kind]: id }));
          setAsrNotice(null);
        } else if (state === "unavailable") {
          setAsrNotice(`${kind}: ${id} unavailable${detail ? ` — ${detail}` : ""}`);
        }
        return;
      }
      // Record client-side arrival time per event type for the pipeline "active" glow.
      activityRef.current[e.type] = Date.now();
      if (e.type === "dialogue.state") {
        setDialogue({
          state: e.payload.state,
          text: e.payload.text ?? "",
          model: e.payload.model,
          timing: e.payload.timing,
        });
        return; // dialogue.state is pipeline telemetry, not a face-driving event
      }
      if (e.type === "asr.source") {
        // Whisper loads lazily on the backend; reflect loading/active/error here.
        setAsrLoading(e.payload.state === "loading");
        if (e.payload.state === "active") setAsrSource(e.payload.source ?? null);
        return;
      }
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

  const notices = [
    mic.error && { tone: "err", text: `mic: ${mic.error}` },
    speech.error && { tone: "err", text: `stt: ${speech.error}` },
    vision.error && { tone: "err", text: `camera: ${vision.error}` },
    asrNotice && { tone: "warn", text: asrNotice },
  ].filter(Boolean) as { tone: string; text: string }[];

  return (
    // Column: fixed-height bar, then the stage takes the rest. `min-h-0` is what lets the
    // face shrink to fit instead of overflowing — without it the canvas keeps its natural
    // height and the face ends up below the fold on a 720 px window.
    <div className="flex h-full w-full flex-col overflow-hidden">
      <TopBar
        status={status}
        wsUrl={WS_URL}
        listening={listening}
        onToggleListen={toggleListen}
        watching={vision.active}
        watchLoading={vision.loading}
        onToggleWatch={() => (vision.active ? vision.stop() : vision.start())}
        settingsOpen={settingsOpen}
        onToggleSettings={() => setSettingsOpen((v) => !v)}
        pipelineOpen={showPanel}
        onTogglePipeline={() => setShowPanel((v) => !v)}
        devOpen={dev}
        onToggleDev={() => setDev((v) => !v)}
      />

      <div className="relative min-h-0 flex-1">
        {/* The face is laid out on its own and never reflows: panels overlay it, so the
            framing is identical whether they are open or closed. */}
        <div ref={headRef} className="h-full w-full will-change-transform">
          <VizijRuntimeFace />
        </div>

        {/* One dock, one treatment. Panels sit side by side so the pipeline stays
            readable while a setting is changed. */}
        <PanelDock>
          <SettingsDrawer
            open={settingsOpen}
            onClose={() => setSettingsOpen(false)}
            registry={pipeline?.providers}
            active={{ ...activeProviders, asr: asrSource ?? activeProviders.asr }}
            busyKind={asrLoading ? "asr" : null}
            onSelect={setProvider}
          />
          {showPanel && (
            <PipelinePanel
              onClose={() => setShowPanel(false)}
              pipeline={pipeline}
              mode={mode}
              listening={listening}
              partial={speech.partial}
              log={log}
              dialogue={dialogue}
              activityRef={activityRef}
              asrSource={asrSource}
              activeProviders={activeProviders}
              watching={vision.active}
            />
          )}
          {dev && (
            <DevControls
              onClose={() => setDev(false)}
              debug={{
                sayText,
                setSayText,
                say,
                userText,
                setUserText,
                simulateUserTurn,
              }}
            />
          )}
        </PanelDock>

        <CameraPreview stream={vision.stream} log={log} frames={vision.frames} />

        {/* Notices float rather than growing the bar, which is what pushed the face down. */}
        {notices.length > 0 && (
          <div className="absolute bottom-3 left-3 z-20 space-y-1 text-xs">
            {notices.map((n, i) => (
              <div
                key={i}
                className={`rounded px-2 py-1 backdrop-blur ${
                  n.tone === "err"
                    ? "bg-red-950/80 text-red-200"
                    : "bg-amber-950/80 text-amber-200"
                }`}
              >
                {n.text}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function FaceStage() {
  // Wraps the face canvas so the driver can apply head motion (nod/shake/tilt) as a
  // transform — the rig's head transform isn't writable from this runtime build.
  const headRef = useRef<HTMLDivElement | null>(null);
  return (
    <VizijRuntimeProvider assetBundle={assetBundle} autostart>
      <ReticoBridge headRef={headRef} />
    </VizijRuntimeProvider>
  );
}
