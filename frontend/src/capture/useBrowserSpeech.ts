import { useCallback, useRef, useState } from "react";
import type { WsClient } from "../net/wsClient";

// Browser-side speech-to-text via the Web Speech API (Chrome: webkitSpeechRecognition).
// Interim results are surfaced locally (for the "listening…" display); only final
// transcripts are sent to the backend as `input.asr`, where BrowserASRModule turns them
// into the same SpeechRecognitionIU stream the Whisper path produces.
//
// This is independent of useMicCapture: the recognizer opens its own mic capture, while
// useMicCapture streams raw PCM for turn-taking. Both run together when listening.

// The Web Speech API isn't in the default TS DOM lib, so type the bits we use loosely.
type SR = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  onresult: ((e: any) => void) | null;
  onerror: ((e: any) => void) | null;
  onend: (() => void) | null;
};

function getSRClass(): (new () => SR) | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

// Errors that mean this browser will never produce results (as opposed to routine
// silence), so the caller can fall back to backend ASR instead of failing silently.
const FATAL_ERRORS = new Set([
  "not-allowed",
  "service-not-allowed",
  "audio-capture",
  "network",
  "language-not-supported",
]);

export function useBrowserSpeech(getWs: () => WsClient | null) {
  const supported = typeof window !== "undefined" && !!getSRClass();
  const [listening, setListening] = useState(false);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [results, setResults] = useState(0); // finals delivered — proves it works
  const srRef = useRef<SR | null>(null);
  const wantRef = useRef(false); // keep restarting while the user wants to listen

  const stop = useCallback(() => {
    wantRef.current = false;
    try {
      srRef.current?.stop();
    } catch {
      /* ignore */
    }
    srRef.current = null;
    setListening(false);
    setPartial("");
  }, []);

  const start = useCallback(() => {
    const SRClass = getSRClass();
    if (!SRClass) {
      setError("Web Speech API not supported in this browser (use Chrome, or ASR_SOURCE=whisper).");
      return;
    }
    const sr = new SRClass();
    sr.continuous = true;
    sr.interimResults = true;
    sr.lang = "en-US";
    sr.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        const text = res[0]?.transcript ?? "";
        if (res.isFinal) {
          const final = text.trim();
          if (final) {
            setResults((n) => n + 1);
            getWs()?.sendJSON({ type: "input.asr", payload: { text: final, final: true } });
          }
        } else {
          interim += text;
        }
      }
      setPartial(interim.trim());
    };
    sr.onerror = (e: any) => {
      // "no-speech"/"aborted" are routine; surface the rest.
      const code = e?.error ? String(e.error) : "";
      if (code && code !== "no-speech" && code !== "aborted") {
        setError(code);
        // A fatal code means retrying won't help — stop looping and let the caller
        // fall back to backend ASR rather than sitting there transcribing nothing.
        if (FATAL_ERRORS.has(code)) {
          wantRef.current = false;
          setFatal(code);
        }
      }
    };
    sr.onend = () => {
      setPartial("");
      // The API stops itself after silence; restart while the user still wants to listen.
      if (wantRef.current) {
        try {
          sr.start();
        } catch {
          /* already starting */
        }
      } else {
        setListening(false);
      }
    };
    wantRef.current = true;
    srRef.current = sr;
    try {
      sr.start();
      setListening(true);
      setError(null);
      setFatal(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [getWs]);

  // An explicit "use the browser recognizer" deserves a real attempt: `fatal` is sticky
  // (it is only cleared by a *successful* start), so without this a single transient
  // service-not-allowed made the option permanently unselectable — picking it bounced
  // straight back to a backend ASR before the recognizer was ever asked again.
  const clearFatal = useCallback(() => setFatal(null), []);

  return { supported, listening, partial, error, fatal, clearFatal, results, start, stop };
}
