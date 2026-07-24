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
import { DevControls } from "./devControls";
import { ExplainPanel } from "./ExplainPanel";

// Our own GLB, hosted under frontend/public/assets/.
const GLB_URL = `${import.meta.env.BASE_URL}assets/face.glb`;
const WS_URL = `ws://${location.hostname}:8770/ws`;

const assetBundle: VizijAssetBundle = {
  namespace: "vizij-retico",
  glb: { kind: "url", src: GLB_URL, aggressiveImport: true },
  pose: { stageNeutralFilter: (_id, path) => !path.includes("/color/") },
};

/** Registers the retico input driver and owns the WebSocket connection. */
function ReticoBridge() {
  const rt = useVizijRuntime();
  const [status, setStatus] = useState<WsStatus>("connecting");
  const [last, setLast] = useState<ReticoEvent | null>(null);
  const [log, setLog] = useState<ReticoEvent[]>([]);
  const [mode, setMode] = useState<string | null>(null);
  const rtRef = useRef(rt);
  rtRef.current = rt;
  const startedRef = useRef(false);
  const wsRef = useRef<WsClient | null>(null);
  const mic = useMicCapture(() => wsRef.current);
  const [sayText, setSayText] = useState("Hi there! I can talk now.");

  const say = () => {
    const text = sayText.trim();
    if (text) wsRef.current?.sendJSON({ type: "control", action: "say", text });
  };

  // Connect the WebSocket once on mount, independent of the runtime lifecycle
  // (reconnect handles drops). Decoupling from `ready` avoids the socket being torn
  // down when the device recomposes during load.
  useEffect(() => {
    const ws = new WsClient(WS_URL);
    wsRef.current = ws;
    const offStatus = ws.onStatus(setStatus);
    const offEvent = ws.addEventListener((e) => {
      if ((e as { type?: string }).type === "hello") {
        setMode((e as { mode?: string }).mode ?? null);
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
    const { registerInputDriver, animateValue, assetBundle, faceId, inputConstraints } =
      rtRef.current;
    const controls = resolveFaceControls(assetBundle, faceId, inputConstraints);
    console.log("[vizij-retico] resolved face controls", controls);
    const lifecycle = registerInputDriver(
      "retico",
      createReticoDriver(wsRef.current, controls, animateValue),
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
      <ExplainPanel mode={mode} log={log} />
    <div className="absolute left-3 top-3 rounded bg-neutral-950/70 px-3 py-2 text-xs text-neutral-100 backdrop-blur">
      <div className="flex items-center gap-2">
        <span className={`inline-block h-2 w-2 rounded-full ${dot}`} />
        <span>retico {status}</span>
        <span className="opacity-60">{WS_URL}</span>
        <button
          className={`ml-2 rounded px-2 py-0.5 ${mic.active ? "bg-emerald-600" : "bg-neutral-700"} hover:opacity-90`}
          onClick={() => (mic.active ? mic.stop() : mic.start())}
        >
          {mic.active ? "● mic on" : "mic off"}
        </button>
      </div>
      {mic.error && <div className="mt-1 text-red-300">mic: {mic.error}</div>}
      <div className="mt-2 flex gap-1">
        <input
          className="w-56 rounded bg-neutral-800 px-2 py-1 text-neutral-100 outline-none"
          value={sayText}
          onChange={(e) => setSayText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && say()}
          placeholder="type something to say…"
        />
        <button className="rounded bg-teal-700 px-2 py-1 hover:bg-teal-600" onClick={say}>
          say
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
  return (
    <VizijRuntimeProvider assetBundle={assetBundle} autostart>
      <div className="relative h-full w-full">
        <VizijRuntimeFace />
        <ReticoBridge />
        <button
          className="absolute right-3 top-3 rounded bg-neutral-700 px-2 py-1 text-xs text-neutral-100 hover:bg-neutral-600"
          onClick={() => setDev((d) => !d)}
        >
          {dev ? "hide dev" : "dev"}
        </button>
        {dev && <DevControls />}
      </div>
    </VizijRuntimeProvider>
  );
}
