import { useEffect, useRef, useState } from "react";
import {
  VizijRuntimeProvider,
  VizijRuntimeFace,
  useVizijRuntime,
  type VizijAssetBundle,
} from "@vizij/runtime-react";
import { WsClient, type ReticoEvent, type WsStatus } from "../net/wsClient";
import { createReticoDriver } from "../drivers/VizijReticoDriver";
import { useMicCapture } from "../capture/useMicCapture";
import { DevControls } from "./devControls";

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
  const rtRef = useRef(rt);
  rtRef.current = rt;
  const startedRef = useRef(false);
  const wsRef = useRef<WsClient | null>(null);
  const mic = useMicCapture(() => wsRef.current);

  // Register the driver + open the socket exactly once, when the runtime becomes
  // ready. We read the (unstable-identity) runtime methods through a ref so this
  // effect doesn't re-run — re-registering the driver recomposes the device.
  useEffect(() => {
    if (!rt.ready || startedRef.current) return;
    startedRef.current = true;
    const { registerInputDriver, inputConstraints, animateValue } = rtRef.current;
    const ws = new WsClient(WS_URL);
    wsRef.current = ws;
    const offStatus = ws.onStatus(setStatus);
    const offEvent = ws.addEventListener(setLast);
    const inputPaths = Object.keys(inputConstraints ?? {});
    const lifecycle = registerInputDriver(
      "retico",
      createReticoDriver(ws, inputPaths, animateValue),
    );
    lifecycle.start(); // idempotent
    ws.connect();
    return () => {
      offStatus();
      offEvent();
      lifecycle.dispose();
      ws.close();
      wsRef.current = null;
      startedRef.current = false;
    };
  }, [rt.ready]);

  const dot = status === "open" ? "bg-emerald-400" : status === "connecting" ? "bg-amber-400" : "bg-red-400";
  return (
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
