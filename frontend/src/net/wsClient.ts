// Bidirectional WebSocket client for the retico bridge:
// - receives JSON event envelopes (turn.state / backchannel.cue / nod.cue / ...)
// - sends captured audio upstream as binary PCM frames.
// Reconnects with backoff so the driver survives backend restarts.

export type ReticoEvent = {
  v: number;
  type: string;
  ts: number;
  seq: number;
  iu: { id: string; prev: string | null; update: string } | null;
  payload: Record<string, any>;
};

export type WsStatus = "connecting" | "open" | "closed";

export class WsClient {
  private ws: WebSocket | null = null;
  private closed = false;
  private backoff = 500;
  private listeners = new Set<(e: ReticoEvent) => void>();
  private statusCbs = new Set<(s: WsStatus) => void>();

  constructor(private url: string) {}

  addEventListener(fn: (e: ReticoEvent) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  onStatus(fn: (s: WsStatus) => void): () => void {
    this.statusCbs.add(fn);
    return () => this.statusCbs.delete(fn);
  }

  private emitStatus(s: WsStatus) {
    this.statusCbs.forEach((f) => f(s));
  }

  connect(): void {
    this.closed = false;
    this.open();
  }

  private open(): void {
    this.emitStatus("connecting");
    const ws = new WebSocket(this.url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      this.backoff = 500;
      this.emitStatus("open");
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return; // ignore any binary echo
      let parsed: ReticoEvent;
      try {
        parsed = JSON.parse(ev.data);
      } catch {
        return;
      }
      this.listeners.forEach((f) => f(parsed));
    };
    ws.onclose = () => {
      this.emitStatus("closed");
      this.ws = null;
      if (!this.closed) {
        this.backoff = Math.min(this.backoff * 2, 5000);
        setTimeout(() => this.open(), this.backoff);
      }
    };
    ws.onerror = () => ws.close();
  }

  /** Send raw PCM (int16 mono @ 16k) upstream. */
  sendAudio(pcm: ArrayBuffer): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(pcm);
  }

  /** Send a JSON control message (e.g. { type:"control", action:"say", text }). */
  sendJSON(obj: unknown): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
    this.ws = null;
  }
}
