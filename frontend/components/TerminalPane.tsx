"use client";

/* Shared Company OS build terminal. Connects to the original coding PTY when
   available, so the browser sees the same bytes the autonomous agent sees. */

import { useEffect, useRef, useState } from "react";
import { getAuthToken, waitForAuthReady } from "@/lib/api";
import "@xterm/xterm/css/xterm.css";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function terminalWsUrl(sessionId: string, token: string, recovery = false): string {
  // Derive ws(s):// from the API origin; route /terminal/ through nginx → backend.
  let base = API;
  if (base.startsWith("https://")) base = "wss://" + base.slice(8);
  else if (base.startsWith("http://")) base = "ws://" + base.slice(7);
  else {
    // NEXT_PUBLIC_API_URL is "/api" in production (relative, same-origin) --
    // naively prepending "wss://" onto a leading-slash path produces
    // "wss:///api" (empty host, invalid URL) and the socket fails instantly
    // with no request ever reaching the backend. Resolve it against the
    // current page's own origin instead.
    const proto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = typeof window !== "undefined" ? window.location.host : "";
    base = `${proto}//${host}${base.startsWith("/") ? base : `/${base}`}`;
  }
  return `${base}/terminal/${encodeURIComponent(sessionId)}?token=${encodeURIComponent(token)}${recovery ? "&recovery=1" : ""}`;
}

export default function TerminalPane({ sessionId, onClose, compact = false }: { sessionId: string; onClose: () => void; compact?: boolean }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "closed" | "error">("connecting");
  const [shared, setShared] = useState(false);
  const [recovery, setRecovery] = useState(false);
  const [rawProtocol, setRawProtocol] = useState(false);
  const rawProtocolRef = useRef(false);
  const protocolBuffer = useRef("");

  useEffect(() => { rawProtocolRef.current = rawProtocol; }, [rawProtocol]);

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
      term.write(`\x1b[2m connecting to ${recovery ? "interactive Caveman" : "the coding agent"}…\x1b[0m\r\n`);
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
      ws = new WebSocket(terminalWsUrl(sessionId, token, recovery));
      ws.binaryType = "arraybuffer";

      ws.onopen = () => { setStatus("live"); sendResize(); term?.focus(); };
      ws.onmessage = (ev) => {
        if (!term) return;
        if (typeof ev.data === "string") {
          // Control/error frames arrive as JSON text.
          try {
            const m = JSON.parse(ev.data);
            if (m?.t === "terminal_state") {
              setShared(Boolean(m.shared));
              setStatus(m.state === "live" ? "live" : "closed");
              const terminalKind = m.shared ? "shared live build terminal" : m.state === "completed" ? "completed build transcript" : "build terminal";
              term.write(`\r\n\x1b[2m[${terminalKind} · ${m.state}${m.workspace ? ` · ${m.workspace}` : ""}]\x1b[0m\r\n`);
            } else if (m?.t === "error") term.write(`\r\n\x1b[31m[${m.message}]\x1b[0m\r\n`);
          }
          catch { term.write(ev.data); }
        } else {
          const bytes = new Uint8Array(ev.data as ArrayBuffer);
          if (rawProtocolRef.current || recovery) {
            term.write(bytes);
            return;
          }
          const text = new TextDecoder().decode(bytes);
          protocolBuffer.current += text.replace(/\r/g, "");
          const lines = protocolBuffer.current.split("\n");
          protocolBuffer.current = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const event = JSON.parse(line);
              const type = String(event.type ?? event.kind ?? "");
              const tool = String(event.toolName ?? event.tool ?? "");
              const args = event.args ?? {};
              if (type === "tool_execution_start") {
                const target = args.path ?? args.file_path ?? args.command ?? args.query ?? "";
                term.write(`\x1b[36mtool\x1b[0m ${tool || "working"}${target ? ` · ${String(target).slice(0, 180)}` : ""}\r\n`);
              } else if (type === "tool_execution_end") {
                term.write(`\x1b[32mdone\x1b[0m ${tool || "tool"}\r\n`);
              } else if (type === "message_end") {
                const usage = event.message?.usage ?? event.usage ?? {};
                const tokens = Number(usage.input ?? 0) + Number(usage.output ?? 0);
                term.write(`\x1b[35magent\x1b[0m completed a coding turn${tokens ? ` · ${tokens.toLocaleString()} tokens` : ""}\r\n`);
              } else if (type === "error" || event.isError) {
                term.write(`\x1b[31merror\x1b[0m ${String(event.message ?? event.error ?? "Agent step failed").slice(0, 500)}\r\n`);
              } else if (type === "session" || type === "turn_start") {
                term.write(`\x1b[2magent ${type === "turn_start" ? "started a turn" : "session connected"}\x1b[0m\r\n`);
              }
            } catch {
              // Non-protocol output is useful (npm/build errors), so preserve it.
              term.write(`${line.slice(0, 1200)}\r\n`);
            }
          }
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
  }, [sessionId, recovery]);

  const dot = status === "live" ? "#34d399" : status === "connecting" ? "#fcd34d" : "#f87171";
  const label = status === "live" ? (recovery ? "interactive Caveman session" : "live agent trace") : status === "connecting" ? "connecting to live build…" : status === "closed" ? "build completed — transcript is read-only" : "connection error";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, fontFamily: "var(--font-mono, monospace)", color: "var(--fm)" }}>
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: dot, display: "inline-block" }} />
        <span>{label}</span>
        <span style={{ flex: 1 }} />
        {!recovery && <button onClick={() => setRawProtocol(value => !value)} style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)", color: "var(--fm)", background: "transparent", border: 0, cursor: "pointer" }}>{rawProtocol ? "Readable trace" : "Raw protocol"}</button>}
        {status === "closed" && !recovery && <button onClick={() => setRecovery(true)} style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)", color: "var(--accent)", background: "transparent", border: "1px solid var(--bd)", borderRadius: 6, padding: "2px 8px", cursor: "pointer" }}>Continue in Caveman</button>}
        <button
          onClick={onClose}
          style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)", color: "var(--fd)", background: "transparent", border: "1px solid rgba(0,0,0,.15)", borderRadius: 6, padding: "2px 10px", cursor: "pointer" }}
        >
          Release ✕
        </button>
      </div>
      <div ref={hostRef} style={{ background: "#0c0d10", borderRadius: 8, padding: 8, height: compact ? 96 : "60vh", overflow: "hidden" }} />
    </div>
  );
}
