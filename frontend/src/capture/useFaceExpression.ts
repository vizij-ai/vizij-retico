import { useCallback, useRef, useState } from "react";
import { FaceLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";
import type { WsClient } from "../net/wsClient";

// Facial expression recognition in the browser, via MediaPipe Face Landmarker.
//
// Only the 52 blendshape coefficients are sent to the backend — never the image. That is
// a privacy property worth having (the camera feed never leaves the machine) and it also
// keeps the bandwidth trivial compared with streaming video for server-side FER.
//
// Turning those coefficients into an emotion happens on the backend, so the
// perception→affect step stays a retico module (see backend/vizij_retico/fer.py).

// MediaPipe fetches its WASM runtime and model from a CDN. That is an external runtime
// dependency; to run fully offline, vendor these into public/ and point at them instead.
const WASM_BASE =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

/** Expression is continuous; ~6 Hz is plenty for driving a face and keeps traffic small. */
const SEND_INTERVAL_MS = 160;

export function useFaceExpression(
  getWs: () => WsClient | null,
  /** Backend FER provider. EmoNet needs the actual image; MediaPipe does not. */
  getSource: () => string = () => "browser",
) {
  const [active, setActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [frames, setFrames] = useState(0);
  // Exposed so the UI can show a preview — seeing what the camera sees makes it
  // obvious whether a null reading is the model or just a badly framed face.
  const [stream, setStream] = useState<MediaStream | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const landmarkerRef = useRef<FaceLandmarker | null>(null);
  const rafRef = useRef<number>(0);
  const lastSentRef = useRef(0);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wantRef = useRef(false);

  const stop = useCallback(() => {
    wantRef.current = false;
    cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setStream(null);
    videoRef.current?.remove();
    videoRef.current = null;
    setActive(false);
    setFrames(0);
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: "user" },
      });
      streamRef.current = stream;
      setStream(stream);

      // Offscreen video element: we only need frames to feed the landmarker.
      const video = document.createElement("video");
      video.srcObject = stream;
      video.muted = true;
      video.playsInline = true;
      await video.play();
      videoRef.current = video;

      if (!landmarkerRef.current) {
        const fileset = await FilesetResolver.forVisionTasks(WASM_BASE);
        landmarkerRef.current = await FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
          outputFaceBlendshapes: true,
          runningMode: "VIDEO",
          numFaces: 1,
        });
      }

      wantRef.current = true;
      setActive(true);
      setLoading(false);

      const pump = () => {
        if (!wantRef.current) return;
        const landmarker = landmarkerRef.current;
        const el = videoRef.current;
        if (landmarker && el && el.readyState >= 2) {
          const now = performance.now();
          const due = now - lastSentRef.current > SEND_INTERVAL_MS;
          if (due && getSource() === "emonet") {
            // EmoNet runs server-side and needs pixels, so this path *does* upload the
            // image — the privacy advantage belongs to the MediaPipe path only.
            lastSentRef.current = now;
            const canvas = (canvasRef.current ??= document.createElement("canvas"));
            canvas.width = 320;
            canvas.height = 240;
            canvas.getContext("2d")?.drawImage(el, 0, 0, canvas.width, canvas.height);
            const data = canvas.toDataURL("image/jpeg", 0.7).split(",")[1];
            getWs()?.sendJSON({ type: "input.video", payload: { data } });
            setFrames((n) => n + 1);
          } else if (due) {
            // Only run the landmarker when its output is actually used — in EmoNet mode
            // the server does the inference and this would be wasted work every frame.
            const result = landmarker.detectForVideo(el, now);
            const categories = result.faceBlendshapes?.[0]?.categories;
            if (categories) {
              lastSentRef.current = now;
              const blendshapes: Record<string, number> = {};
              for (const c of categories) {
                // Drop near-zero coefficients — most of the 52 are idle at any moment.
                if (c.score > 0.02 && c.categoryName)
                  blendshapes[c.categoryName] = +c.score.toFixed(3);
              }
              getWs()?.sendJSON({ type: "input.fer", payload: { blendshapes } });
              setFrames((n) => n + 1);
            }
          }
        }
        rafRef.current = requestAnimationFrame(pump);
      };
      pump();
    } catch (err: unknown) {
      setLoading(false);
      setError(err instanceof Error ? err.message : String(err));
      stop();
    }
  }, [getWs, getSource, stop]);

  return { active, loading, error, frames, stream, start, stop };
}
