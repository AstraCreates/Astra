"use client";

// LLC Filing Modal — live browser stream. Founder-supervised only: this
// connects to the real Northwest Registered Agent filing automation and
// requires the founder to watch the live browser and answer each prompt
// themselves (see backend/api/routes.py's /ws/llc-filing endpoint and
// backend/specialists/legal_entity.py for why the autonomous agent path
// never drives this directly).
//
// Extracted out of GoalWorkspace.tsx so PhaseWorkboard.tsx (the actual
// day-to-day dashboard) can reuse it instead of needing its own duplicate
// copy — the two views drifting apart is exactly why this card went missing
// from PhaseWorkboard in the first place.

import { useEffect, useRef, useState } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type FilingPhase = "connecting" | "running" | "interaction_needed" | "bot_filling" | "payment_filling" | "done" | "error";

interface FilingFieldOption { value: string; label: string; description?: string; }
interface FilingField { name: string; label: string; type: string; required?: boolean; options?: FilingFieldOption[]; default?: string; price?: string; placeholder?: string; show_if?: string; }

export default function LLCFilingModal({ founderId, companyName, state, onClose }: {
  founderId: string; companyName: string; state: string; onClose: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [phase, setPhase] = useState<FilingPhase>("connecting");
  const [stepName, setStepName] = useState("Starting…");
  const [stepNum, setStepNum] = useState(0);
  const [message, setMessage] = useState("");
  const [fields, setFields] = useState<FilingField[]>([]);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [confirmationUrl, setConfirmationUrl] = useState("");

  const STEPS_TOTAL = 7;

  useEffect(() => {
    const wsBase = BASE.replace("https://", "wss://").replace("http://", "ws://");
    const params = new URLSearchParams({ company_name: companyName, state });
    const ws = new WebSocket(`${wsBase}/llc/stream/${founderId}?${params}`);
    wsRef.current = ws;

    ws.onopen = () => setPhase("running");
    ws.onerror = () => { setPhase("error"); setMessage("WebSocket connection failed."); };
    ws.onclose = () => { if (phase !== "done" && phase !== "error") setPhase("error"); };

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);

      if (msg.type === "frame") {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        const img = new Image();
        img.onload = () => {
          canvas.width = img.naturalWidth || 1280;
          canvas.height = img.naturalHeight || 800;
          ctx.drawImage(img, 0, 0);
        };
        img.src = `data:image/jpeg;base64,${msg.data}`;
        return;
      }

      if (msg.type === "status") {
        setStepName(msg.step); setStepNum(msg.step_num);
        setPhase("running"); setMessage("");
      } else if (msg.type === "interaction_needed") {
        setStepName(msg.step); setMessage(msg.message);
        setFields(msg.fields || []); setPhase("interaction_needed");
      } else if (msg.type === "bot_filling") {
        setPhase("running"); setMessage("Bot is filling your information…");
      } else if (msg.type === "payment_filling") {
        setPhase("payment_filling"); setMessage(msg.message || "Filling payment securely…");
      } else if (msg.type === "done") {
        setPhase("done");
        setConfirmationUrl(msg.confirmation_url || "");
        setMessage(msg.message || "LLC filed successfully!");
      } else if (msg.type === "error") {
        setPhase("error"); setMessage(msg.message || "An error occurred.");
      }
    };

    return () => { ws.close(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submitInput = () => {
    const data = { ...formValues };
    // For untouched selects: prefer field.default, then first available option
    fields.forEach(f => {
      if (f.type === "select" && !data[f.name]) {
        if (f.default) data[f.name] = f.default;
        else if (f.options?.[0]) data[f.name] = f.options[0].value;
      }
    });
    const missing = fields.filter(f => f.required && f.type !== "select" && !data[f.name]?.trim());
    if (missing.length > 0) { setFormError(`Required: ${missing.map(f => f.label).join(", ")}`); return; }
    setSubmitting(true); setFormError("");
    wsRef.current?.send(JSON.stringify({ type: "founder_input", data }));
    setPhase("bot_filling");
    setSubmitting(false);
  };

  const isLocked = phase !== "interaction_needed";
  const stepPercent = STEPS_TOTAL > 0 ? Math.round((stepNum / STEPS_TOTAL) * 100) : 0;

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999,
      background: "rgba(0,0,0,0.85)", backdropFilter: "blur(12px)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 24, flexDirection: "column", gap: 0,
    }}>
      <div style={{
        width: "100%", maxWidth: 1000,
        maxHeight: "calc(100vh - 48px)",
        background: "var(--glass)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)",
        border: "1px solid var(--line)", borderRadius: 24,
        boxShadow: "var(--shadow-lg)", overflow: "hidden",
        display: "flex", flexDirection: "column",
      }}>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: "1px solid var(--line-2)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 16 }}>≡</span>
            <div>
              <span style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)" }}>Filing LLC — {companyName}</span>
              <span style={{ fontSize: 11, color: "var(--fg-mute)", marginLeft: 10, fontFamily: "var(--font-mono)" }}>{state}</span>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {/* Step indicator */}
            <span style={{ fontSize: 11, color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>
              {stepNum > 0 ? `Step ${stepNum}/${STEPS_TOTAL} — ${stepName}` : stepName}
            </span>
            {phase !== "done" && (
              <button onClick={() => { wsRef.current?.close(); onClose(); }}
                className="site-btn site-btn-ghost" style={{ fontSize: 11, padding: "0 12px", minHeight: 28 }}>
                Cancel
              </button>
            )}
          </div>
        </div>

        {/* Progress bar */}
        <div style={{ height: 3, background: "var(--line-2)" }}>
          <div style={{
            height: "100%", borderRadius: 999, width: "100%",
            transform: `scaleX(${(phase === "done" ? 100 : stepPercent) / 100})`, transformOrigin: "left",
            transition: "transform 0.6s cubic-bezier(0.22,1,0.36,1)",
            background: phase === "done" ? "linear-gradient(90deg,#4ade80,#22d3ee)" : "linear-gradient(90deg,#60a5fa,#a78bfa)",
          }} />
        </div>

        {/* Browser canvas area */}
        <div style={{ position: "relative", background: "#0a0a0a", minHeight: 300, flex: "1 1 auto", overflow: "auto" }}>

          {/* Live canvas */}
          <canvas ref={canvasRef}
            style={{
              width: "100%", height: "auto", maxHeight: "55vh", objectFit: "contain", display: "block",
              filter: phase === "payment_filling" ? "blur(12px) brightness(0.3)" : "none",
              transition: "filter 0.4s",
              pointerEvents: "none",
            }}
          />

          {/* Lock overlay — blocks interaction when bot is running */}
          {isLocked && phase !== "done" && phase !== "error" && (
            <div style={{
              position: "absolute", inset: 0,
              background: "transparent",
              cursor: "not-allowed",
              zIndex: 10,
            }} />
          )}

          {/* Connecting state */}
          {phase === "connecting" && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12 }}>
              <div style={{ width: 32, height: 32, border: "3px solid rgba(255,255,255,0.15)", borderTopColor: "#60a5fa", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
              <span style={{ fontSize: 13, color: "rgba(255,255,255,0.5)" }}>Connecting to browser…</span>
            </div>
          )}

          {/* Payment filling overlay */}
          {phase === "payment_filling" && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 16, zIndex: 20 }}>
              <div style={{ padding: "20px 32px", borderRadius: 20, background: "rgba(0,0,0,0.7)", border: "1px solid rgba(255,255,255,0.1)", textAlign: "center" }}>
                <div style={{ fontSize: 28, marginBottom: 10 }}>🔒</div>
                <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#fff" }}>Filling payment securely</p>
                <p style={{ margin: "6px 0 0", fontSize: 12, color: "rgba(255,255,255,0.5)" }}>Astra is paying for your LLC filing. Browser hidden for security.</p>
              </div>
            </div>
          )}

          {/* Done overlay */}
          {phase === "done" && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 16, zIndex: 20, background: "rgba(0,0,0,0.6)" }}>
              <div style={{ padding: "24px 36px", borderRadius: 24, background: "rgba(0,0,0,0.8)", border: "1px solid rgba(74,222,128,0.3)", textAlign: "center", maxWidth: 420 }}>
                <div style={{ fontSize: 40, marginBottom: 12 }}>🎉</div>
                <p style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "#4ade80" }}>LLC Filed!</p>
                <p style={{ margin: "8px 0 0", fontSize: 13, color: "rgba(255,255,255,0.6)", lineHeight: 1.6 }}>
                  {confirmationUrl ? `Confirmation: ${confirmationUrl}` : message || "Your LLC has been submitted to Northwest Registered Agent."}
                </p>
                <button onClick={onClose} className="site-btn site-btn-primary" style={{ marginTop: 16, padding: "0 24px", fontSize: 13 }}>
                  Close
                </button>
              </div>
            </div>
          )}

          {/* Error overlay */}
          {phase === "error" && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12, zIndex: 20, background: "rgba(0,0,0,0.6)" }}>
              <div style={{ padding: "20px 28px", borderRadius: 20, background: "rgba(0,0,0,0.8)", border: "1px solid rgba(248,113,113,0.3)", textAlign: "center", maxWidth: 400 }}>
                <div style={{ fontSize: 28, marginBottom: 8 }}>⚠</div>
                <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#f87171" }}>Filing error</p>
                <p style={{ margin: "6px 0 0", fontSize: 12, color: "rgba(255,255,255,0.5)" }}>{message}</p>
                <button onClick={onClose} className="site-btn" style={{ marginTop: 12, fontSize: 12, padding: "0 16px", color: "#f87171", background: "rgba(248,113,113,0.1)", borderColor: "rgba(248,113,113,0.2)" }}>
                  Close
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Interaction needed — bottom panel slides up */}
        {phase === "interaction_needed" && (
          <div style={{
            borderTop: "2px solid rgba(96,165,250,0.4)",
            background: "rgba(15,20,40,0.97)",
            padding: "18px 24px",
            flexShrink: 0,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#60a5fa", flexShrink: 0, animation: "blink 1.2s infinite" }} />
              <span style={{ fontSize: 13, fontWeight: 600, color: "#60a5fa" }}>Your turn — {message}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {fields.map((field, i) => {
                // hide SSN field until "yes" is selected for has_ssn
                if (field.show_if && (formValues["has_ssn"] ?? "yes") !== field.show_if) return null;
                const spanFull = field.type === "password" || field.type === "select" || field.type === "disclaimer";
                return (
                  <div key={field.name} style={{ display: "flex", flexDirection: "column", gap: 4, gridColumn: spanFull ? "span 2" : undefined }}>

                    {field.type === "disclaimer" ? (
                      <div style={{
                        padding: "10px 12px", borderRadius: 9, fontSize: 11, lineHeight: 1.6,
                        background: "rgba(251,191,36,0.08)", border: "1px solid rgba(251,191,36,0.2)",
                        color: "rgba(251,191,36,0.85)",
                      }}>{field.label}</div>
                    ) : field.type === "select" && field.options ? (
                      <>
                        <label style={{ fontSize: 11, fontWeight: 500, color: "rgba(255,255,255,0.45)" }}>
                          {field.label}{field.required && <span style={{ color: "#f87171", marginLeft: 2 }}>*</span>}
                        </label>
                        <div style={{ display: "flex", gap: 8 }}>
                          {field.options.map(opt => {
                            const selected = (formValues[field.name] ?? field.default) === opt.value;
                            return (
                              <button key={opt.value} onClick={() => setFormValues(v => ({ ...v, [field.name]: opt.value }))}
                                style={{
                                  flex: 1, padding: "10px 12px", borderRadius: 10, cursor: "pointer", textAlign: "left",
                                  background: selected ? "rgba(96,165,250,0.2)" : "rgba(255,255,255,0.05)",
                                  border: selected ? "1px solid rgba(96,165,250,0.6)" : "1px solid rgba(255,255,255,0.1)",
                                  color: selected ? "#93c5fd" : "rgba(255,255,255,0.6)",
                                }}>
                                <div style={{ fontSize: 13, fontWeight: 600 }}>{opt.label}</div>
                                {opt.description && <div style={{ fontSize: 11, marginTop: 3, opacity: 0.7 }}>{opt.description}</div>}
                              </button>
                            );
                          })}
                        </div>
                      </>
                    ) : (
                      <>
                        <label style={{ fontSize: 11, fontWeight: 500, color: "rgba(255,255,255,0.45)" }}>
                          {field.label}{field.required && <span style={{ color: "#f87171", marginLeft: 2 }}>*</span>}
                        </label>
                        <input
                          autoFocus={i === 0}
                          type={field.type}
                          placeholder={field.placeholder ?? ""}
                          value={formValues[field.name] ?? ""}
                          onChange={e => setFormValues(v => ({ ...v, [field.name]: e.target.value }))}
                          onKeyDown={e => { if (e.key === "Enter") submitInput(); }}
                          style={{
                            padding: "9px 12px", fontSize: 13, borderRadius: 9,
                            background: "rgba(255,255,255,0.07)",
                            border: "1px solid rgba(255,255,255,0.15)",
                            color: "#fff", outline: "none", width: "100%",
                          }}
                          autoComplete="new-password"
                        />
                      </>
                    )}
                  </div>
                );
              })}
            </div>
            {formError && <p style={{ margin: "8px 0 0", fontSize: 11, color: "#f87171" }}>{formError}</p>}
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
              <button onClick={submitInput} disabled={submitting}
                style={{
                  padding: "10px 28px", borderRadius: 10, border: "none",
                  background: "linear-gradient(135deg,#3b82f6,#6366f1)",
                  color: "#fff", fontSize: 13, fontWeight: 600,
                  cursor: submitting ? "wait" : "pointer",
                }}>
                {submitting ? "Submitting…" : "Submit & continue →"}
              </button>
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
      `}</style>
    </div>
  );
}
