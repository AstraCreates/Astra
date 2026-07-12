"use client";

/* Interactive openclaude takeover terminal.
   Connects to the backend WS /terminal/{sessionId}, renders the live PTY with
   xterm.js, forwards keystrokes, and reflows on resize. The backend resumes the
   agent's openclaude session so the founder drives the exact same conversation. */

import { useEffect, useRef, useState } from "react";
import { getAuthToken, waitForAuthReady } from "@/lib/api";
import "@xterm/xterm/css/xterm.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function terminalWsUrl(sessionId: string, token: string): string {
  // Derive ws(s):// from the API origin; route /terminal/ through nginx → backend.
  let base = API;
  if (base.startsWith("https://")) base = "wss://" + base.slice(8);
  else if (base.startsWith("http://")) base = "ws://" + base.slice(7);
  else base = (typeof window !== "undefined" && window.location.protocol === "https:" ? "wss://" : "ws://") + base;
  return `${base}/terminal/${encodeURIComponent(sessionId)}?token=${encodeURIComponent(token)}`;
}

export default function TerminalPane({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "closed" | "error">("connecting");

  useEffect(() => {
    let term: import("@xterm/xterm").Terminal | null = null;
    let fit: import("@xterm/addon-fit").FitAddon | null = null;
    let ws: WebSocket | null = null;
    let ro: ResizeObserver | null = null;
    let disposed = false;

    (async () => {
      const { Terminal } = await import("@xterm/xterm");
      const { FitAddon } = await import("@xterm/addon-fit");
      if (disposed || !hostRef.current) return;

      term = new Terminal({
        fontFamily: "var(--font-mono, ui-monospace, monospace)",
        fontSize: 12,
        cursorBlink: true,
        theme: { background: "#0c0d10", foreground: "#d4d4d8", cursor: "#7dd3fc" },
        scrollback: 5000,
      });
      fit = new FitAddon();
      term.loadAddon(fit);
      term.open(hostRef.current);
      term.write("\x1b[2m connecting to openclaude…\x1b[0m\r\n");
      // Refit after the container has its final layout size (avoids a 0×0 grid
      // that renders as a black box on first paint).
      requestAnimationFrame(() => { try { fit?.fit(); } catch {} });

      const sendResize = () => {
        if (!fit || !term || !ws || ws.readyState !== WebSocket.OPEN) return;
        try { fit.fit(); } catch {}
        ws.send(JSON.stringify({ t: "resize", cols: term.cols, rows: term.rows }));
      };

      // WebSocket cannot carry Authorization headers. Wait for the auth bridge's
      // short-lived JWT cache rather than treating a founder identifier as proof.
      await waitForAuthReady(2000);
      const token = getAuthToken();
      if (!token) {
        term.write("\r\n\x1b[31m[Authentication token unavailable. Please sign in again.]\x1b[0m\r\n");
        setStatus("error");
        return;
      }
      ws = new WebSocket(terminalWsUrl(sessionId, token));
      ws.binaryType = "arraybuffer";

      ws.onopen = () => { setStatus("live"); sendResize(); term?.focus(); };
      ws.onmessage = (ev) => {
        if (!term) return;
        if (typeof ev.data === "string") {
          // Control/error frames arrive as JSON text.
          try { const m = JSON.parse(ev.data); if (m?.t === "error") term.write(`\r\n\x1b[31m[${m.message}]\x1b[0m\r\n`); }
          catch { term.write(ev.data); }
        } else {
          term.write(new Uint8Array(ev.data as ArrayBuffer));
        }
      };
      ws.onclose = () => { if (!disposed) setStatus("closed"); };
      ws.onerror = () => { if (!disposed) setStatus("error"); };

      // Keystrokes → backend (binary frames).
      term.onData((d) => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(d));
      });

      ro = new ResizeObserver(() => sendResize());
      ro.observe(hostRef.current);
    })();

    return () => {
      disposed = true;
      try { ro?.disconnect(); } catch {}
      try { ws?.close(); } catch {}
      try { term?.dispose(); } catch {}
    };
  }, [sessionId]);

  const dot = status === "live" ? "#34d399" : status === "connecting" ? "#fcd34d" : "#f87171";
  const label = status === "live" ? "live — you are driving openclaude" : status === "connecting" ? "connecting…" : status === "closed" ? "session ended" : "connection error";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, fontFamily: "var(--font-mono, monospace)", color: "var(--fm)" }}>
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: dot, display: "inline-block" }} />
        <span>{label}</span>
        <span style={{ flex: 1 }} />
        <button
          onClick={onClose}
          style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)", color: "var(--fd)", background: "transparent", border: "1px solid rgba(0,0,0,.15)", borderRadius: 6, padding: "2px 10px", cursor: "pointer" }}
        >
          Release ✕
        </button>
      </div>
      <div ref={hostRef} style={{ background: "#0c0d10", borderRadius: 8, padding: 8, height: "60vh", overflow: "hidden" }} />
    </div>
  );
}
