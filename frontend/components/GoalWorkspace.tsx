"use client";

import { useCallback, useEffect, useState, useRef, useSyncExternalStore } from "react";
import type { CSSProperties } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { SignInButton, useUser } from "@clerk/nextjs";
import { streamGoal, continueSession, submitGoal, AGENT_LABELS, AGENT_ORDER, TOOL_DESCRIPTIONS, sortAgentNamesByOrder } from "@/lib/api";
import { saveSession, getSessionSnapshot, subscribeSessions, deleteSession, clearAllSessions } from "@/lib/history";
import type { SessionRecord } from "@/lib/history";
import LiquidGlass from "@/components/LiquidGlass";
import CompanyChat from "@/components/CompanyChat";
import ThemeToggle from "@/components/ThemeToggle";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface AgentTask { id: string; agent: string; instruction: string; }

interface LogEntry { ts: number; type: string; text: string; }

interface AgentState {
  task_id: string;
  agent: string;
  instruction: string;
  status: "waiting" | "running" | "done" | "error";
  currentAction: string | null;
  currentTool: string | null;
  reasoning: string | null;
  result: Record<string, unknown> | null;
  log: LogEntry[];
  mirrorVerdict?: "pass" | "flag" | "block";
  mirrorCritique?: string;
  currentUrl?: string;
  visitedUrls?: string[];
  previewUrl?: string;
  colors?: string[];
  commits?: string[];
  filesPreview?: string[];
  filesCount?: number;
  socialContent?: Record<string, string>;
  legalText?: string;
  salesLead?: string;
  designSpec?: string;
  adImages?: Array<{ url?: string; base64?: string; prompt?: string }>;
  webQualityError?: string;
}

const PREVIEW_CARD: React.CSSProperties = {
  borderRadius: 12,
  border: "1px solid rgba(0,0,0,0.08)",
  background: "rgba(255,255,255,0.03)",
  padding: "10px 12px",
};

const PREVIEW_HEADER: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.1em",
  textTransform: "uppercase",
  color: "var(--fg-mute)",
};

const AGENT_ICONS: Record<string, string> = {
  research: "🔬", research_competitors: "🏆", research_execution: "📋",
  web: "🌐", marketing: "📢", technical: "⚙️",
  legal: "⚖️", ops: "🚀", sales: "🤝", design: "🎨",
};

const STATUS_COLOR = {
  waiting: "rgba(0,0,0,0.2)",
  running: "#2563EB",
  done: "#3D9E5F",
  error: "#C0392B",
};

const STACK_OPTIONS = {
  frontend: ["Next.js", "React + Vite", "SvelteKit", "Remix"],
  backend: ["FastAPI", "Express / Node", "Django", "Serverless"],
  database: ["Supabase (Postgres)", "PlanetScale (MySQL)", "MongoDB", "SQLite"],
  auth: ["Clerk", "Supabase Auth", "NextAuth", "Custom JWT"],
};

const STARTER_PROMPTS = [
  {
    title: "Waitlist SaaS",
    prompt: "Build a waitlist SaaS for creators — landing page, Next.js app, Supabase DB, Clerk auth, Vercel deploy.",
  },
  {
    title: "Invoice tool",
    prompt: "Launch a B2B invoice automation tool — repo, database, auth, landing page, three investor emails.",
  },
  {
    title: "Matching platform",
    prompt: "Build a real-time co-founder matching platform with live URL, auth, and a pitch deck PDF.",
  },
];

function pct(state: AgentState): number {
  if (state.status === "done") return 100;
  if (state.status === "waiting") return 0;
  const steps = Math.max(state.log.filter(l => l.type === "result" || l.type === "action").length, 1);
  return Math.min(90, Math.round((steps / 12) * 90));
}

function extractColors(log: LogEntry[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const l of log) {
    const matches = l.text.match(/#([0-9a-fA-F]{6})\b/g) ?? [];
    for (const c of matches) { if (!seen.has(c)) { seen.add(c); out.push(c); } }
  }
  return out;
}

function extractHexFromObj(obj: unknown, depth = 0): string[] {
  if (depth > 4 || !obj || typeof obj !== "object") return [];
  return Object.values(obj as Record<string, unknown>).flatMap(v => {
    if (typeof v === "string") {
      // exact hex value OR hex codes embedded inside a longer string
      if (/^#[0-9a-fA-F]{6}$/.test(v)) return [v];
      return Array.from(v.matchAll(/#[0-9a-fA-F]{6}\b/g), m => m[0]);
    }
    return extractHexFromObj(v, depth + 1);
  });
}

// Find the first nested object that has ≥2 hex string values — that's the color palette
function findPalette(obj: unknown, depth = 0): Record<string, string> | null {
  if (depth > 4 || !obj || typeof obj !== "object") return null;
  const entries = Object.entries(obj as Record<string, unknown>);
  const hexEntries = entries.filter(([, v]) => typeof v === "string" && /^#[0-9a-fA-F]{6}$/.test(v as string));
  if (hexEntries.length >= 2) return Object.fromEntries(hexEntries) as Record<string, string>;
  for (const [, v] of entries) {
    const found = findPalette(v, depth + 1);
    if (found) return found;
  }
  return null;
}

function extractUrls(log: LogEntry[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const l of log) {
    const matches = l.text.match(/https?:\/\/[^\s"')\]]+/g) ?? [];
    for (const u of matches) {
      const clean = u.replace(/[.,;]+$/, "");
      if (!seen.has(clean) && !clean.includes("localhost")) { seen.add(clean); out.push(clean); }
    }
  }
  return out;
}

function faviconUrl(url: string): string | null {
  try { return `https://www.google.com/s2/favicons?domain=${new URL(url).hostname}&sz=16`; } catch { return null; }
}

function summarizeResult(state: AgentState | undefined): string {
  if (!state) return "No active agent selected.";
  if (state.status === "waiting") return "This agent has not started yet.";
  if (state.status === "error") return "This lane hit an error and needs a rerun or steer.";

  const result = state.result ?? {};
  const previewUrl = (result.url ?? result.deployment_url ?? result.project_url ?? result.github_url) as string | undefined;
  if (previewUrl) return `Primary output available at ${previewUrl.replace(/^https?:\/\//, "")}.`;
  if (state.visitedUrls?.length) return `${state.visitedUrls.length} sites visited so far for this lane.`;
  if (state.commits?.length) return `${state.commits.length} code rounds committed so far.`;
  if (Object.keys(result).length) return `${Object.keys(result).length} output fields captured in this lane.`;
  return state.currentAction ? `Currently ${state.currentAction}.` : "This lane is in progress.";
}

function extractAdImagesFromResult(obj: unknown, seen = new Set<string>()): Array<{ url?: string; base64?: string; prompt?: string }> {
  if (!obj || typeof obj !== "object") return [];
  const o = obj as Record<string, unknown>;
  const results: Array<{ url?: string; base64?: string; prompt?: string }> = [];
  // Check if this object looks like an image result
  const resolvedUrl = (typeof o.url === "string" && o.url) || (typeof o.image_url === "string" && o.image_url) || "";
  const hasImageUrl = /^https?:/.test(resolvedUrl);
  const hasBase64 = typeof o.base64 === "string" && o.base64.length > 100;
  if (hasImageUrl || hasBase64) {
    const key = resolvedUrl || (o.base64 as string).slice(0, 50);
    if (!seen.has(key)) {
      seen.add(key);
      results.push({ url: resolvedUrl || undefined, base64: o.base64 as string | undefined, prompt: o.prompt as string | undefined });
    }
  }
  for (const v of Object.values(o)) {
    results.push(...extractAdImagesFromResult(v, seen));
  }
  return results;
}

// ── Agent-specific preview panels ──────────────────────────────────────────

function ResearchPreview({ state }: { state: AgentState }) {
  const urls = extractUrls(state.log);
  const current = state.currentUrl ?? urls[urls.length - 1];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, height: "100%" }}>
      {current && (
        <div style={{ borderRadius: 28, overflow: "hidden", border: "1px solid rgba(0,0,0,0.09)", background: "#FFFFFF" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderBottom: "1px solid rgba(0,0,0,0.07)", background: "rgba(180,205,228,0.10)" }}>
            {faviconUrl(current) && <img src={faviconUrl(current)!} width={12} height={12} style={{ opacity: 0.6 }} onError={e => (e.currentTarget.style.display = "none")} />}
            <span style={{ fontSize: 11, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{current}</span>
            <a href={current} target="_blank" rel="noopener noreferrer" style={{ fontSize: 10, color: "#2563EB", textDecoration: "none" }}>↗</a>
          </div>
          <div style={{ height: 280, position: "relative" }}>
            <iframe
              src={current}
              sandbox="allow-scripts allow-same-origin"
              style={{ width: "100%", height: "100%", border: "none", opacity: 0.95 }}
              title="Research preview"
            />
            <div style={{ position: "absolute", inset: 0, pointerEvents: "none", background: "linear-gradient(to bottom, transparent 80%, rgba(232,232,230,0.7))" }} />
          </div>
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 160, overflowY: "auto" }}>
        <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", marginBottom: 4 }}>Sites visited ({urls.length})</span>
        {urls.map((u, i) => (
          <a key={i} href={u} target="_blank" rel="noopener noreferrer" style={{ display: "flex", alignItems: "center", gap: 8, borderRadius: 6, padding: "5px 8px", background: u === current ? "rgba(180,205,228,0.10)" : "rgba(255,255,255,0.28)", border: `1px solid ${u === current ? "rgba(180,205,228,0.22)" : "rgba(255,255,255,0.45)"}`, textDecoration: "none" }}>
            {faviconUrl(u) && <img src={faviconUrl(u)!} width={12} height={12} onError={e => (e.currentTarget.style.display = "none")} />}
            <span style={{ fontSize: 11, color: "var(--fg-dim)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{u.replace(/^https?:\/\//, "").slice(0, 60)}</span>
          </a>
        ))}
        {urls.length === 0 && state.status === "running" && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--fg-mute)" }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#2563EB" }} className="animate-pulse" /> Searching…
          </div>
        )}
      </div>
    </div>
  );
}

function WebPreview({ state }: { state: AgentState }) {
  const url = state.previewUrl ?? (state.result?.url ?? state.result?.deployment_url ?? state.result?.project_url) as string | undefined;
  const commits = state.commits ?? [];
  const usedFallback = state.log.some(l => l.text.includes("fallback template"));
  const qualityError = state.webQualityError ?? (state.result?.web_quality_error as string | undefined);
  if (url) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10, height: "100%" }}>
        {qualityError && (
          <div style={{ borderRadius: 10, border: "1px solid rgba(192,57,43,0.3)", background: "rgba(192,57,43,0.08)", padding: "8px 10px", fontSize: 11, color: "#C97070" }}>
            Web quality gate failed: {qualityError.replace(/_/g, " ")}
          </div>
        )}
        {usedFallback && (
          <div style={{ borderRadius: 10, border: "1px solid rgba(192,57,43,0.3)", background: "rgba(192,57,43,0.08)", padding: "8px 10px", fontSize: 11, color: "#C97070" }}>
            Fallback template was detected in this run. A quality retry should follow.
          </div>
        )}
        <div style={{ borderRadius: 28, overflow: "hidden", border: "1px solid rgba(0,0,0,0.09)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 12px", background: "rgba(180,205,228,0.10)", borderBottom: "1px solid rgba(0,0,0,0.07)" }}>
            <div style={{ display: "flex", gap: 5 }}>
              {["#ff5f57","#febc2e","#28c840"].map(c => <div key={c} style={{ width: 10, height: 10, borderRadius: "50%", background: c }} />)}
            </div>
            <span style={{ fontSize: 11, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)", flex: 1, textAlign: "center", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{url}</span>
            <a href={url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 10, color: "#2563EB", textDecoration: "none" }}>↗</a>
          </div>
          <div style={{ height: 340, background: "#FFFFFF" }}>
            <iframe src={url} style={{ width: "100%", height: "100%", border: "none" }} title="Site preview" />
          </div>
        </div>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {commits.length > 0 ? (
        <>
          <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Recent commits</span>
          {commits.map((c, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", borderRadius: 6, background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.08)" }}>
              <span style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: 10, color: "#2563EB" }}>●</span>
              <span style={{ fontSize: 11, color: "var(--fg-dim)" }}>{c}</span>
            </div>
          ))}
        </>
      ) : (
        <BuildingIndicator label="Building site…" />
      )}
    </div>
  );
}

function TechnicalPreview({ state }: { state: AgentState }) {
  const r = state.result ?? {};
  // LLM role says return deploy_url; also check other key variants
  const deploy = (r.deploy_url ?? r.deployment_url ?? r.project_url ?? r.url) as string | undefined;
  const repo = (r.repo_url ?? r.github_url) as string | undefined;
  const roundsRun = (r.rounds_run ?? r.rounds) as number | undefined;
  const filesCount = (r.files_in_repo as number) ?? state.filesCount;
  const files = state.filesPreview ?? (Array.isArray(r.files_preview) ? r.files_preview as string[] : undefined);
  const commits = state.commits ?? [];
  const isBuilding = state.status === "running";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ ...PREVIEW_CARD, display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 10px" }}>
        <span style={PREVIEW_HEADER}>Technical Build</span>
        <span style={{ fontSize: 11, color: state.status === "done" ? "#3D9E5F" : "#2563EB", fontWeight: 600 }}>
          {state.status === "done" ? "Complete" : state.status === "running" ? "Running" : "Queued"}
        </span>
      </div>
      {(isBuilding || state.currentTool) && (
        <div style={{ borderRadius: 12, border: "1px solid rgba(37,99,235,0.2)", background: "rgba(37,99,235,0.08)", padding: "8px 10px", display: "grid", gap: 4 }}>
          <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "#2563EB" }}>Live build status</div>
          <div style={{ fontSize: 12, color: "var(--fg-dim)" }}>
            {state.currentTool ? `Running ${state.currentTool.replace(/_/g, " ")}` : "Preparing build pipeline"}
          </div>
          {state.log.length > 0 && (
            <div style={{ fontSize: 10, color: "var(--fg-mute)" }}>
              {state.log.slice(-1)[0]?.text?.slice(0, 140)}
            </div>
          )}
        </div>
      )}
      {/* Live site iframe */}
      {deploy && (
        <div style={{ borderRadius: 20, overflow: "hidden", border: "1px solid rgba(37,99,235,0.18)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 12px", background: "rgba(180,205,228,0.10)", borderBottom: "1px solid rgba(0,0,0,0.07)" }}>
            <div style={{ display: "flex", gap: 4 }}>
              {["#ff5f57","#febc2e","#28c840"].map(c => <div key={c} style={{ width: 9, height: 9, borderRadius: "50%", background: c }} />)}
            </div>
            <span style={{ fontSize: 10, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)", flex: 1, textAlign: "center", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{deploy.replace(/^https?:\/\//, "")}</span>
            <a href={deploy} target="_blank" rel="noopener noreferrer" style={{ fontSize: 10, color: "#2563EB", textDecoration: "none", flexShrink: 0 }}>↗</a>
          </div>
          <iframe src={deploy} style={{ width: "100%", height: 280, border: "none", display: "block" }} title="Live MVP" />
        </div>
      )}

      {/* Stats row */}
      {(repo || filesCount || roundsRun || commits.length > 0) && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
          {[
            ["Commits", commits.length || "—"],
            ["Files", filesCount ?? "—"],
            ["Rounds", roundsRun ?? "—"],
          ].map(([label, val]) => (
            <div key={label as string} style={{ padding: "8px 10px", borderRadius: 12, background: "rgba(180,205,228,0.08)", border: "1px solid rgba(180,205,228,0.14)", textAlign: "center" }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "var(--fg)", fontFamily: "var(--font-jetbrains-mono)" }}>{val}</div>
              <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--fg-mute)", marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* GitHub repo link */}
      {repo && (
        <a href={repo} target="_blank" rel="noopener noreferrer" style={{ display: "flex", alignItems: "center", gap: 8, borderRadius: 20, border: "1px solid rgba(0,0,0,0.1)", background: "rgba(0,0,0,0.03)", padding: "8px 14px", color: "#2563EB", textDecoration: "none", fontSize: 12 }}>
          <span>🐙</span>
          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{repo.replace("https://github.com/", "")}</span>
          <span style={{ opacity: 0.5, flexShrink: 0 }}>↗</span>
        </a>
      )}

      {/* File tree */}
      {files && files.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 1, maxHeight: 180, overflowY: "auto" }}>
          <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", marginBottom: 4 }}>Files built ({files.length})</span>
          {files.map((f, i) => (
            <div key={i} style={{ fontSize: 10, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)", padding: "2px 6px", display: "flex", alignItems: "center", gap: 6 }}>
              <span>{f.startsWith("frontend/") ? "🔷" : f.startsWith("backend/") ? "🔶" : "📄"}</span>
              <span>{f}</span>
            </div>
          ))}
        </div>
      )}

      {/* Commits log */}
      {commits.length > 0 && !deploy && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Build commits</span>
          {commits.slice(-5).map((c, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", borderRadius: 6, background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.07)" }}>
              <span style={{ fontFamily: "var(--font-jetbrains-mono)", fontSize: 10, color: "#2563EB" }}>{c.slice(0, 7)}</span>
              <span style={{ fontSize: 10, color: "var(--fg-mute)" }}>committed</span>
            </div>
          ))}
        </div>
      )}

      {state.log.length > 0 && (
        <div style={{ display: "grid", gap: 4 }}>
          <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Recent technical activity</span>
          {state.log.slice(-5).map((entry, i) => (
            <div key={i} style={{ padding: "5px 9px", borderRadius: 6, fontSize: 10, color: "var(--fg-mute)", background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.06)" }}>
              {entry.text.slice(0, 140)}
            </div>
          ))}
        </div>
      )}

      {!repo && !deploy && !isBuilding && <ResultDump result={state.result} />}
      {!repo && !deploy && isBuilding && <BuildingIndicator label="Building MVP with openclaude…" />}
    </div>
  );
}

function DesignPreview({ state }: { state: AgentState }) {
  const result = state.result ?? {};

  // Find the color palette anywhere in the result (LLM may nest under any key)
  const rawPalette = findPalette(result) ?? null;

  const paletteEntries = rawPalette ? Object.entries(rawPalette) : [];
  const paletteHexes = paletteEntries.map(([, v]) => v);
  const logHexes = extractColors(state.log);
  const resultHexes = extractHexFromObj(result);
  const allColors = [...new Set([...paletteHexes, ...logHexes, ...resultHexes])];

  const spec = (
    state.designSpec ??
    result.design_spec ??
    result.spec ??
    result.design_system ??
    result.css_variables
  ) as string | undefined;
  const wireframes = (result.wireframes ?? result.pages ?? result.screen_specs) as Array<Record<string, unknown>> | undefined;
  const logoBriefObj = result.logo_brief as Record<string, unknown> | undefined;
  const logoBrief = (typeof logoBriefObj === "object" ? JSON.stringify(logoBriefObj, null, 2) : (result.logo_brief ?? result.brand_direction ?? result.logo_direction)) as string | undefined;

  const isDone = state.status === "done";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ ...PREVIEW_CARD, display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6, padding: "8px 10px" }}>
        {[
          ["Colors", String(allColors.length)],
          ["Wireframes", String(Array.isArray(wireframes) ? wireframes.length : 0)],
          ["Spec", spec ? "Yes" : "No"],
        ].map(([k, v]) => (
          <div key={k} style={{ textAlign: "center" }}>
            <div style={{ fontSize: 9, textTransform: "uppercase", color: "var(--fg-mute)", letterSpacing: "0.08em" }}>{k}</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--fg)" }}>{v}</div>
          </div>
        ))}
      </div>
      {allColors.length > 0 && (
        <div>
          {/* Gradient hero bar using the palette */}
          <div style={{ height: 52, borderRadius: 14, marginBottom: 10, background: `linear-gradient(135deg, ${allColors.slice(0,4).join(", ")})`, boxShadow: `0 4px 24px ${allColors[0]}55` }} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(56px, 1fr))", gap: 6 }}>
            {allColors.slice(0, 10).map((c, i) => (
              <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
                <div style={{ width: "100%", aspectRatio: "1", borderRadius: 10, background: c, boxShadow: `0 4px 12px ${c}66, inset 0 1px 0 rgba(255,255,255,0.15)` }} />
                <span style={{ fontSize: 8, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)", textAlign: "center" }}>{c}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {paletteEntries.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {paletteEntries.map(([k, v]) => (
            <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", borderRadius: 8, background: `${v}14`, border: `1px solid ${v}33` }}>
              <div style={{ width: 16, height: 16, borderRadius: 4, background: v, boxShadow: `0 2px 6px ${v}66`, flexShrink: 0 }} />
              <span style={{ fontSize: 10, color: "var(--fg-dim)", textTransform: "capitalize", flex: 1 }}>{k.replace(/_/g, " ")}</span>
              <span style={{ fontSize: 10, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)" }}>{v}</span>
            </div>
          ))}
        </div>
      )}
      {spec && (
        <div>
          <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", display: "block", marginBottom: 6 }}>Design Spec</span>
          <div style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.7, whiteSpace: "pre-wrap", maxHeight: 200, overflowY: "auto", padding: "10px 12px", background: "rgba(180,205,228,0.10)", borderRadius: 24, border: "1px solid rgba(0,0,0,0.08)" }}>
            {typeof spec === "string" ? spec.slice(0, 600) : JSON.stringify(spec, null, 2).slice(0, 600)}
          </div>
        </div>
      )}
      {Array.isArray(wireframes) && wireframes.length > 0 && (
        <div style={{ display: "grid", gap: 6 }}>
          <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Wireframes</span>
          {wireframes.slice(0, 5).map((wf, i) => (
            <div key={i} style={{ borderRadius: 10, border: "1px solid rgba(0,0,0,0.08)", background: "rgba(255,255,255,0.03)", padding: "8px 10px", fontSize: 11, color: "var(--fg-dim)" }}>
              <div style={{ fontWeight: 600, color: "var(--fg)" }}>{String(wf.page ?? wf.name ?? `Screen ${i + 1}`)}</div>
              <div>{String(wf.layout ?? wf.structure ?? wf.notes ?? "").slice(0, 140)}</div>
            </div>
          ))}
        </div>
      )}
      {logoBrief && (
        <div style={{ borderRadius: 10, border: "1px solid rgba(0,0,0,0.08)", background: "rgba(255,255,255,0.03)", padding: "8px 10px", fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.6 }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)", marginBottom: 4 }}>Logo direction</div>
          {logoBrief.slice(0, 320)}
        </div>
      )}
      {allColors.length === 0 && !spec && isDone && <ResultDump result={state.result} />}
      {allColors.length === 0 && !spec && !isDone && <BuildingIndicator label="Building design system…" tool={state.currentTool ?? undefined} />}
    </div>
  );
}

function MarketingPreview({ state }: { state: AgentState }) {
  const r = state.result ?? {};

  // LLM may nest content under reel_package/tiktok_package/meta_ad or at top level
  const reelPkg = (r.reel_package ?? r.reel ?? r.instagram_reel ?? {}) as Record<string, unknown>;
  const tiktokPkg = (r.tiktok_package ?? r.tiktok ?? {}) as Record<string, unknown>;
  const metaAdPkg = (r.meta_ad ?? r.ad ?? {}) as Record<string, unknown>;
  const emailPkg = (r.email_campaign ?? r.email ?? {}) as Record<string, unknown>;

  // Reel: check nested pkg first, then top-level
  const reelScript = (reelPkg.script ?? r.script ?? r.reel_script ?? "") as string;
  const reelCaption = (reelPkg.caption ?? r.caption ?? r.reel_caption ?? "") as string;
  const rawHashtags = reelPkg.hashtags ?? r.hashtags;
  const reelHashtags = Array.isArray(rawHashtags) ? (rawHashtags as string[]).join(" ") : (rawHashtags as string ?? "");

  // TikTok
  const tiktokScript = (tiktokPkg.script ?? r.tiktok_script ?? "") as string;

  // Meta ad
  const adHeadline = (metaAdPkg.headline ?? r.headline ?? r.ad_headline ?? "") as string;
  const adBody = (metaAdPkg.primary_text ?? r.primary_text ?? r.ad_body ?? r.ad_copy ?? "") as string;
  const adCta = (metaAdPkg.cta ?? r.cta ?? "") as string;

  // Email
  const emailSubject = (emailPkg.subject ?? r.subject ?? r.email_subject ?? "") as string;
  const rawEmailBody = emailPkg.text ?? emailPkg.html ?? r.text ?? r.email_text ?? r.email_body ?? r.html ?? "";
  const emailBody = (rawEmailBody) as string;

  // LinkedIn post
  const linkedin = (r.linkedin_post ?? r.post_text ?? r.linkedin ?? "") as string;

  const hasContent = reelScript || reelCaption || tiktokScript || adHeadline || adBody || emailSubject || emailBody || linkedin;
  const isDone = state.status === "done";

  if (!hasContent) {
    return isDone ? <ResultDump result={state.result} /> : <BuildingIndicator label="Creating campaigns…" tool={state.currentTool ?? undefined} />;
  }

  const SocialCard = ({ platform, icon, color, gradient, lines }: { platform: string; icon: string; color: string; gradient: string; lines: [string, string][] }) => (
    <div style={{ borderRadius: 16, overflow: "hidden", border: `1px solid ${color}33` }}>
      <div style={{ padding: "8px 12px", background: gradient, display: "flex", alignItems: "center", gap: 7 }}>
        <span style={{ fontSize: 14 }}>{icon}</span>
        <span style={{ fontSize: 11, fontWeight: 700, color: "#fff", letterSpacing: "0.03em" }}>{platform}</span>
      </div>
      <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8, background: "rgba(255,255,255,0.02)" }}>
        {lines.filter(([, v]) => v).map(([k, v]) => (
          <div key={k}>
            <span style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--fg-mute)" }}>{k}</span>
            <p style={{ margin: "3px 0 0", fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.65, whiteSpace: "pre-wrap", maxHeight: 90, overflowY: "auto" }}>{v.slice(0, 350)}</p>
          </div>
        ))}
      </div>
    </div>
  );

  const CARD = (label: string, lines: [string, string][]) => (
    <div style={{ ...PREVIEW_CARD, display: "flex", flexDirection: "column", gap: 8 }}>
      <span style={{ fontSize: 11, fontWeight: 700, color: "var(--fg)", letterSpacing: "0.03em" }}>{label}</span>
      {lines.filter(([, v]) => v).map(([k, v]) => (
        <div key={k}>
          <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>{k}</span>
          <p style={{ margin: "3px 0 0", fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.6, whiteSpace: "pre-wrap", maxHeight: 100, overflowY: "auto" }}>{v.slice(0, 400)}</p>
        </div>
      ))}
    </div>
  );

  const adImages = state.adImages ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ ...PREVIEW_CARD, display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 10px" }}>
        <span style={PREVIEW_HEADER}>Campaign Output</span>
        <span style={{ fontSize: 11, color: "var(--fg-dim)" }}>{hasContent ? "Assets ready" : "Generating"}</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 6 }}>
        {[
          ["Reels", reelScript ? "1+" : "0"],
          ["TikTok", tiktokScript ? "1+" : "0"],
          ["Ads", adHeadline || adBody ? "1+" : "0"],
          ["Images", String(adImages.length)],
        ].map(([label, value]) => (
          <div key={label} style={{ borderRadius: 8, border: "1px solid rgba(0,0,0,0.08)", background: "rgba(255,255,255,0.03)", padding: "6px 8px" }}>
            <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>{label}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--fg)" }}>{value}</div>
          </div>
        ))}
      </div>
      {adImages.length > 0 && (
        <div style={{ ...PREVIEW_CARD, display: "flex", flexDirection: "column", gap: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--fg)", letterSpacing: "0.03em" }}>Ad Images</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {adImages.map((img, i) => {
              const src = img.url ?? (img.base64 ? `data:image/png;base64,${img.base64}` : null);
              if (!src) return null;
              return (
                <div key={i} style={{ position: "relative", borderRadius: 12, overflow: "hidden", border: "1px solid rgba(0,0,0,0.12)" }}>
                  <img src={src} alt={img.prompt ?? `Ad image ${i + 1}`} style={{ display: "block", maxWidth: 280, maxHeight: 280, objectFit: "cover" }} />
                  {img.prompt && (
                    <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, background: "rgba(0,0,0,0.6)", padding: "4px 8px" }}>
                      <span style={{ fontSize: 9, color: "rgba(255,255,255,0.8)", lineHeight: 1.4 }}>{img.prompt.slice(0, 100)}{img.prompt.length > 100 ? "…" : ""}</span>
                    </div>
                  )}
                  <a href={src} target="_blank" rel="noopener noreferrer" style={{ position: "absolute", top: 6, right: 6, background: "rgba(0,0,0,0.5)", borderRadius: 6, padding: "2px 6px", fontSize: 9, color: "#fff", textDecoration: "none" }}>↗</a>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {(reelScript || reelCaption) && <SocialCard platform="Instagram Reel" icon="📸" color="#E1306C" gradient="linear-gradient(135deg,#833ab4,#fd1d1d,#fcb045)" lines={[["Script", reelScript], ["Caption", reelCaption], ["Hashtags", reelHashtags]]} />}
      {tiktokScript && <SocialCard platform="TikTok" icon="🎵" color="#69C9D0" gradient="linear-gradient(135deg,#010101,#69C9D0)" lines={[["Script", tiktokScript]]} />}
      {(adHeadline || adBody) && <SocialCard platform="Meta Ad" icon="📣" color="#1877F2" gradient="linear-gradient(135deg,#1877F2,#42a5f5)" lines={[["Headline", adHeadline], ["Body", adBody], ["CTA", adCta]]} />}
      {(emailSubject || emailBody) && CARD("📧 Email", [["Subject", emailSubject], ["Body", typeof emailBody === "string" ? emailBody.replace(/<[^>]+>/g, "") : emailBody]])}
      {linkedin && <SocialCard platform="LinkedIn" icon="💼" color="#0A66C2" gradient="linear-gradient(135deg,#0A66C2,#00a0dc)" lines={[["Post", linkedin]]} />}
    </div>
  );
}

/** Extracts all PDF/TXT file paths from any result object (any depth, any key name). */
function extractFilePaths(obj: unknown, seen = new Set<string>()): string[] {
  if (!obj || typeof obj !== "object") return [];
  const paths: string[] = [];
  for (const v of Object.values(obj as Record<string, unknown>)) {
    if (typeof v === "string" && /\.(pdf|txt)$/i.test(v) && v.startsWith("/") && !seen.has(v)) {
      seen.add(v); paths.push(v);
    } else if (v && typeof v === "object") {
      paths.push(...extractFilePaths(v, seen));
    }
  }
  return paths;
}

function fileUrl(pathOrFilename: string): string {
  const name = pathOrFilename.split("/").pop() ?? pathOrFilename;
  return `${BASE}/files/${encodeURIComponent(name)}`;
}

function PdfEmbed({ path, label, height = 340 }: { path: string; label?: string; height?: number }) {
  const url = fileUrl(path);
  const filename = path.split("/").pop() ?? path;
  const isPdf = filename.toLowerCase().endsWith(".pdf");
  return (
    <div style={{ borderRadius: 16, overflow: "hidden", border: "1px solid rgba(0,0,0,0.10)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 14px", background: "rgba(180,205,228,0.10)", borderBottom: "1px solid rgba(0,0,0,0.07)" }}>
        <span style={{ fontSize: 11, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-mute)", flex: 1 }}>📄 {label ?? filename}</span>
        <a href={url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 10, color: "#2563EB", textDecoration: "none", flexShrink: 0 }}>Download ↗</a>
      </div>
      {isPdf
        ? <iframe src={url} style={{ width: "100%", height, border: "none", display: "block" }} title={label ?? filename} />
        : <div style={{ fontSize: 11, color: "var(--fg-dim)", padding: "10px 14px" }}>
            <a href={url} target="_blank" rel="noopener noreferrer" style={{ color: "#2563EB" }}>{filename} ↗</a>
          </div>
      }
    </div>
  );
}

function LegalPreview({ state, founderId, company }: { state: AgentState; founderId?: string; company?: string }) {
  const r = state.result ?? {};
  const [legalTab, setLegalTab] = useState(0);

  type LegalDoc = { label: string; path?: string; text?: string };
  const docs: LegalDoc[] = [];

  const DOC_KEYS: [string, string][] = [
    ["privacy_policy", "Privacy Policy"],
    ["terms_of_service", "Terms of Service"],
    ["founder_agreement", "Founder Agreement"],
    ["nda", "NDA"],
    ["ip_assignment", "IP Assignment"],
    ["safe_note", "SAFE Note"],
  ];

  for (const [key, label] of DOC_KEYS) {
    const entry = r[key] as Record<string, unknown> | string | undefined;
    if (!entry) continue;
    if (typeof entry === "object") {
      const p = (entry.path ?? entry.filename) as string | undefined;
      const text = (entry.content ?? entry.text ?? entry.formatted_text) as string | undefined;
      docs.push({ label, path: p, text });
    } else {
      docs.push({ label, text: String(entry) });
    }
  }

  // documents[] array
  if (docs.length === 0) {
    const docList = r.documents as Array<Record<string, unknown>> | undefined;
    if (Array.isArray(docList)) {
      for (const d of docList) {
        const label = String(d.title ?? d.doc_type ?? d.type ?? "Document");
        const p = (d.path ?? d.filename) as string | undefined;
        docs.push({ label, path: p, text: (d.content ?? d.text) as string | undefined });
      }
    }
  }

  // Single top-level doc
  if (docs.length === 0) {
    const path = (r.path ?? r.privacy_policy_path ?? r.filename) as string | undefined;
    const text = (r.formatted_text ?? r.content ?? r.document_text ?? r.text) as string | undefined;
    const title = String(r.title ?? r.doc_type ?? "Document");
    if (path || text) docs.push({ label: title, path, text });
  }

  // Deep-scan result object for any .pdf/.txt paths
  const deepPaths = extractFilePaths(r);
  for (const p of deepPaths) {
    const name = p.split("/").pop() ?? p;
    const label = name.replace(/[_-]/g, " ").replace(/\.(pdf|txt)$/i, "").replace(/\w\S*/g, w => w.charAt(0).toUpperCase() + w.slice(1));
    if (!docs.find(d => d.path === p)) docs.push({ label, path: p });
  }

  // Scan log for generate_pdf tool output paths
  for (const entry of state.log) {
    if (!entry.text.includes(".pdf") && !entry.text.includes(".txt")) continue;
    const m = entry.text.match(/\/[^\s"'\\]+\.(pdf|txt)/i);
    if (m) {
      const p = m[0];
      const name = p.split("/").pop() ?? p;
      const label = name.replace(/[_-]/g, " ").replace(/\.(pdf|txt)$/i, "").replace(/\w\S*/g, w => w.charAt(0).toUpperCase() + w.slice(1));
      if (!docs.find(d => d.path === p)) docs.push({ label, path: p });
    }
  }

  const [llcOpen, setLlcOpen] = useState(false);
  const [filingState, setFilingState] = useState("Wyoming");

  const LLCCard = founderId ? (
    <div style={{
      padding: "14px 16px", borderRadius: 14,
      background: "linear-gradient(135deg,rgba(96,165,250,0.08),rgba(139,92,246,0.08))",
      border: "1px solid rgba(96,165,250,0.2)", marginBottom: 4,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)", marginBottom: 3 }}>⚖️ File Your LLC</div>
          <div style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.5 }}>
            Astra will automate the filing with Northwest Registered Agent. Takes ~5 min.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
          <select value={filingState} onChange={e => setFilingState(e.target.value)}
            style={{ fontSize: 11, padding: "5px 8px", borderRadius: 7, background: "var(--glass)", border: "1px solid var(--line)", color: "var(--fg)", cursor: "pointer" }}>
            {["Wyoming","Delaware","Texas","Florida","Nevada","California","New York"].map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <button onClick={() => setLlcOpen(true)}
            style={{
              padding: "7px 18px", borderRadius: 9, border: "none", cursor: "pointer",
              background: "linear-gradient(135deg,#3b82f6,#6366f1)",
              color: "#fff", fontSize: 12, fontWeight: 600, whiteSpace: "nowrap",
            }}>
            Start Filing →
          </button>
        </div>
      </div>
      {llcOpen && founderId && (
        <LLCFilingModal
          founderId={founderId}
          companyName={company || "My Company LLC"}
          state={filingState}
          onClose={() => setLlcOpen(false)}
        />
      )}
    </div>
  ) : null;

  if (docs.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {LLCCard}
        {state.status === "done" ? <ResultDump result={state.result} /> : <BuildingIndicator label="Drafting documents…" />}
      </div>
    );
  }

  const active = docs[legalTab] ?? docs[0];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {LLCCard}
      <div style={{ ...PREVIEW_CARD, display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 10px" }}>
        <span style={PREVIEW_HEADER}>Legal Artifacts</span>
        <span style={{ fontSize: 11, color: "var(--fg-dim)" }}>{docs.length} doc{docs.length === 1 ? "" : "s"}</span>
      </div>
      {docs.length > 1 && (
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", borderBottom: "1px solid rgba(0,0,0,0.08)", paddingBottom: 8 }}>
          {docs.map((d, i) => (
            <button key={i} onClick={() => setLegalTab(i)} style={{
              fontSize: 11, padding: "4px 12px", borderRadius: 6, cursor: "pointer",
              border: legalTab === i ? "1px solid rgba(180,205,228,0.22)" : "1px solid transparent",
              background: legalTab === i ? "rgba(180,205,228,0.10)" : "transparent",
              color: legalTab === i ? "var(--fg)" : "var(--fg-mute)", whiteSpace: "nowrap",
            }}>{d.label}</button>
          ))}
        </div>
      )}

      {active.path
        ? <PdfEmbed path={active.path} label={active.label} height={360} />
        : <div style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.7, whiteSpace: "pre-wrap", maxHeight: 340, overflowY: "auto", padding: "12px 14px", background: "rgba(180,205,228,0.10)", borderRadius: 16, border: "1px solid rgba(0,0,0,0.08)" }}>
            {active.text ? String(active.text).slice(0, 3000) : "No content available."}
          </div>
      }
    </div>
  );
}

function SalesPreview({ state }: { state: AgentState }) {
  const r = state.result;
  const leadsArr = r?.leads as Array<Record<string, unknown>> | undefined;
  const firstLead = Array.isArray(leadsArr) ? leadsArr[0] : undefined;
  const lead = (r?.lead ?? r?.company ?? firstLead?.company ?? firstLead?.name ?? firstLead?.title) as string | undefined;
  const seq = r?.sequence ?? r?.outreach_sequence ?? r?.email_sequence ?? (r?.outreach as Record<string, unknown> | undefined)?.sequence;
  const crmContacts = (r?.crm_contacts ?? r?.contacts ?? []) as Array<Record<string, unknown>>;
  const sequences = (r?.sequences ?? []) as Array<Record<string, unknown>>;
  if (!r || !lead) {
    return state.status === "done" ? <ResultDump result={state.result} /> : <BuildingIndicator label="Building outreach…" />;
  }
  const steps: unknown[] = Array.isArray(seq) ? seq : typeof seq === "string" ? (() => { try { return JSON.parse(seq); } catch { return []; } })() : [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ ...PREVIEW_CARD, display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 10px" }}>
        <span style={PREVIEW_HEADER}>Sales Pipeline</span>
        <span style={{ fontSize: 11, color: "var(--fg-dim)" }}>{Array.isArray(leadsArr) ? leadsArr.length : lead ? 1 : 0} lead(s)</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6 }}>
        {[
          ["Leads", String(Array.isArray(leadsArr) ? leadsArr.length : (lead ? 1 : 0))],
          ["Sequence", String(steps.length)],
          ["CRM", String(Array.isArray(crmContacts) ? crmContacts.length : 0)],
        ].map(([label, value]) => (
          <div key={label} style={{ borderRadius: 8, border: "1px solid rgba(0,0,0,0.08)", background: "rgba(255,255,255,0.03)", padding: "6px 8px" }}>
            <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>{label}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--fg)" }}>{value}</div>
          </div>
        ))}
      </div>
      <div style={{ padding: "8px 12px", borderRadius: 24, background: "rgba(180,205,228,0.10)", border: "1px solid rgba(180,205,228,0.22)" }}>
        <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)", marginBottom: 3 }}>Target Lead</div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{lead}</div>
      </div>
      {Array.isArray(leadsArr) && leadsArr.length > 1 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>All leads ({leadsArr.length})</span>
          {leadsArr.slice(0, 5).map((l, i) => (
            <div key={i} style={{ ...PREVIEW_CARD, padding: "6px 10px", fontSize: 11, color: "var(--fg-dim)" }}>
              {String(l.company ?? l.name ?? l.title ?? l.url ?? JSON.stringify(l)).slice(0, 80)}
            </div>
          ))}
        </div>
      )}
      {steps.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>Email Sequence ({steps.length} steps)</span>
          {(steps as Record<string, unknown>[]).slice(0, 4).map((s, i) => (
            <div key={i} style={{ ...PREVIEW_CARD, padding: "8px 10px", background: "rgba(180,205,228,0.10)", border: "1px solid rgba(180,205,228,0.22)" }}>
              <div style={{ fontSize: 10, color: "#2563EB", marginBottom: 3 }}>Day {String(s.send_day ?? i + 1)}</div>
              <div style={{ fontSize: 11, fontWeight: 500, color: "var(--fg)" }}>{String(s.subject ?? "").slice(0, 60)}</div>
              <div style={{ fontSize: 10, color: "var(--fg-mute)", marginTop: 2 }}>{String(s.body ?? "").slice(0, 80)}…</div>
            </div>
          ))}
        </div>
      )}
      {Array.isArray(sequences) && sequences.length > 1 && (
        <div style={{ display: "grid", gap: 4 }}>
          <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>Additional sequences ({sequences.length - 1})</span>
          {sequences.slice(1, 4).map((seqObj, i) => (
            <div key={i} style={{ ...PREVIEW_CARD, padding: "6px 8px", fontSize: 11, color: "var(--fg-dim)" }}>
              {String((seqObj.lead as Record<string, unknown> | undefined)?.company ?? (seqObj.lead as Record<string, unknown> | undefined)?.name ?? `Lead ${i + 2}`)}
            </div>
          ))}
        </div>
      )}
      {Array.isArray(crmContacts) && crmContacts.length > 0 && (
        <div style={{ display: "grid", gap: 4 }}>
          <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)" }}>CRM contacts ({crmContacts.length})</span>
          {crmContacts.slice(0, 4).map((c, i) => (
            <div key={i} style={{ ...PREVIEW_CARD, padding: "6px 8px", fontSize: 11, color: "var(--fg-dim)" }}>
              {String(c.name ?? c.company ?? c.email ?? JSON.stringify(c)).slice(0, 100)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function OpsPreview({ state }: { state: AgentState }) {
  const r = state.result;
  const sop = (r?.SOP ?? r?.content ?? r?.sop ?? r?.summary ?? r?.deliverable ?? r?.pitch_deck ?? r?.investor_summary) as string | undefined;
  const title = (r?.title ?? r?.doc_type) as string | undefined;

  // Collect all PDF/TXT paths: direct keys + deep scan + log
  const allPaths: string[] = [];
  const directPath = (r?.path ?? r?.filename ?? r?.pdf_path ?? r?.file_path ?? r?.output_path) as string | undefined;
  if (directPath) allPaths.push(directPath);
  for (const p of extractFilePaths(r ?? {})) if (!allPaths.includes(p)) allPaths.push(p);
  for (const entry of state.log) {
    const m = entry.text.match(/\/[^\s"'\\]+\.(pdf|txt)/i);
    if (m && !allPaths.includes(m[0])) allPaths.push(m[0]);
  }

  if (!r || (allPaths.length === 0 && !sop)) {
    return state.status === "done" ? <ResultDump result={state.result} /> : <BuildingIndicator label="Handling operations…" />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ ...PREVIEW_CARD, display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 10px" }}>
        <span style={PREVIEW_HEADER}>Operations Deliverables</span>
        <span style={{ fontSize: 11, color: "var(--fg-dim)" }}>{allPaths.length} file(s)</span>
      </div>
      {title && <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{title}</div>}
      {allPaths.map(p => <PdfEmbed key={p} path={p} height={300} />)}
      {sop && (
      <div style={{ ...PREVIEW_CARD, fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.7, whiteSpace: "pre-wrap", maxHeight: 280, overflowY: "auto", background: "rgba(180,205,228,0.10)" }}>
          {String(sop).slice(0, 1200)}
        </div>
      )}
    </div>
  );
}

function ResultDump({ result }: { result: Record<string, unknown> | null }) {
  if (!result || Object.keys(result).length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--fg-mute)" }}>Agent output ({Object.keys(result).length} fields)</span>
      <div style={{ fontSize: 11, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-dim)", lineHeight: 1.65, whiteSpace: "pre-wrap", maxHeight: 320, overflowY: "auto", padding: "10px 14px", background: "rgba(180,205,228,0.10)", borderRadius: 20, border: "1px solid rgba(0,0,0,0.08)" }}>
        {JSON.stringify(result, null, 2).slice(0, 2400)}
      </div>
    </div>
  );
}

function BuildingIndicator({ label, tool }: { label: string; tool?: string | null }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "18px 0" }}>
      <div style={{ height: 2, borderRadius: 999, background: "rgba(37,99,235,0.12)", overflow: "hidden" }}>
        <div style={{ height: "100%", borderRadius: 999, background: "linear-gradient(90deg, #2563EB, #7C3AED, #2563EB)", backgroundSize: "200% 100%", animation: "shimmer 1.8s linear infinite" }} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#2563EB", flexShrink: 0 }} className="animate-pulse" />
        <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>{label}</span>
        {tool && <span style={{ fontSize: 10, color: "#2563EB", fontFamily: "var(--font-jetbrains-mono)", marginLeft: "auto", opacity: 0.8 }}>{tool.replace(/_/g, "_")}</span>}
      </div>
      <style>{`@keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }`}</style>
    </div>
  );
}

function AgentPreview({ state, founderId, company }: { state: AgentState; founderId?: string; company?: string }) {
  switch (state.agent) {
    case "research":
    case "research_competitors":
    case "research_execution":
      return <ResearchPreview state={state} />;
    case "web": return <WebPreview state={state} />;
    case "technical": return <TechnicalPreview state={state} />;
    case "design": return <DesignPreview state={state} />;
    case "marketing": return <MarketingPreview state={state} />;
    case "legal": return <LegalPreview state={state} founderId={founderId} company={company} />;
    case "sales": return <SalesPreview state={state} />;
    case "ops": return <OpsPreview state={state} />;
    default: return <BuildingIndicator label="Working…" />;
  }
}

// ── Agent detail panel ──────────────────────────────────────────────────────

type DetailTab = "preview" | "plan" | "log" | "obsidian";

function AgentDetail({
  state,
  planTask,
  sessionId,
  founderId,
  company,
}: {
  state: AgentState;
  planTask: AgentTask | undefined;
  sessionId: string;
  founderId: string;
  company?: string;
}) {
  const [tab, setTab] = useState<DetailTab>("preview");
  const [obsidianNote, setObsidianNote] = useState<string | null>(null);
  const [obsidianLoading, setObsidianLoading] = useState(false);
  const [obsidianError, setObsidianError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [state.log.length]);

  useEffect(() => {
    if (tab !== "obsidian" || !founderId || !sessionId || !state.agent) return;
    const ctrl = new AbortController();
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      ctrl.abort();
    }, 8000);
    queueMicrotask(() => {
      if (ctrl.signal.aborted) return;
      setObsidianLoading(true);
      setObsidianError(null);
      setObsidianNote(null);
    });
    fetch(`${BASE}/vault/${encodeURIComponent(founderId)}/note?session_id=${encodeURIComponent(sessionId)}&agent=${encodeURIComponent(state.agent)}`, {
      signal: ctrl.signal,
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 404 ? "No Obsidian note exists for this agent yet." : await res.text());
        return res.json();
      })
      .then((data: { content?: string }) => setObsidianNote(data.content ?? ""))
      .catch((err) => {
        if (err instanceof DOMException && err.name === "AbortError" && !timedOut) return;
        setObsidianNote(null);
        setObsidianError(timedOut ? "Obsidian note request timed out. Check that the backend is running." : err instanceof Error ? err.message : "Failed to load Obsidian note.");
      })
      .finally(() => {
        window.clearTimeout(timeout);
        if (!ctrl.signal.aborted || timedOut) setObsidianLoading(false);
      });
    return () => {
      window.clearTimeout(timeout);
      ctrl.abort();
    };
  }, [tab, founderId, sessionId, state.agent]);

  const p = pct(state);
  const isRunning = state.status === "running";
  const isDone = state.status === "done";

  const TAB_STYLE = (active: boolean): React.CSSProperties => ({
    fontSize: 11, fontWeight: 500, letterSpacing: "0.04em", padding: "5px 14px", borderRadius: 6,
    cursor: "pointer", border: active ? "1px solid rgba(180,205,228,0.22)" : "1px solid transparent",
    background: active ? "rgba(180,205,228,0.10)" : "transparent",
    color: active ? "var(--fg)" : "var(--fg-mute)", transition: "all 0.15s",
    boxShadow: active ? "0 1px 3px rgba(0,0,0,0.05)" : "none",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, flex: 1 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 20 }}>{AGENT_ICONS[state.agent] ?? "🤖"}</span>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: "var(--fg)" }}>{AGENT_LABELS[state.agent] ?? state.agent}</span>
            <span style={{ fontSize: 10, fontFamily: "var(--font-jetbrains-mono)", letterSpacing: "0.08em", textTransform: "uppercase", color: STATUS_COLOR[state.status] }}>{state.status}</span>
          </div>
          {state.instruction && (
            <p style={{ margin: "2px 0 0", fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.4 }}>{state.instruction.slice(0, 100)}</p>
          )}
        </div>
        {/* % badge */}
        <div style={{ position: "relative", width: 40, height: 40, flexShrink: 0 }}>
          <svg viewBox="0 0 40 40" style={{ transform: "rotate(-90deg)" }}>
            <circle cx="20" cy="20" r="17" fill="none" stroke="rgba(0,0,0,0.08)" strokeWidth="3" />
            <circle cx="20" cy="20" r="17" fill="none" stroke={isDone ? "#3D9E5F" : "#2563EB"} strokeWidth="3"
              strokeDasharray={`${2 * Math.PI * 17}`}
              strokeDashoffset={`${2 * Math.PI * 17 * (1 - p / 100)}`}
              style={{ transition: "stroke-dashoffset 0.6s" }} />
          </svg>
          <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 600, fontFamily: "var(--font-jetbrains-mono)", color: isDone ? "#3D9E5F" : "var(--fg-mute)" }}>{p}%</span>
        </div>
      </div>

      {/* Progress bar */}
      <div style={{ height: 3, borderRadius: 999, background: "rgba(0,0,0,0.08)", overflow: "hidden" }}>
        <div style={{ height: "100%", borderRadius: 999, width: `${p}%`, background: isDone ? "#3D9E5F" : "#2563EB", transition: "width 0.6s" }} />
      </div>

      {/* Current action pill */}
      {isRunning && state.currentAction && (
        <div style={{ display: "flex", alignItems: "center", gap: 7, borderRadius: 24, background: "rgba(180,205,228,0.10)", padding: "6px 11px", fontSize: 11, color: "var(--fg-dim)", border: "1px solid rgba(180,205,228,0.22)" }}>
          <span style={{ width: 4, height: 4, borderRadius: "50%", background: "#2563EB", flexShrink: 0 }} className="animate-pulse" />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {state.currentTool ? `${state.currentTool.replace(/_/g, " ")}` : state.currentAction}
            {state.currentUrl ? ` — ${state.currentUrl.replace(/^https?:\/\//, "").slice(0, 50)}` : ""}
          </span>
        </div>
      )}

      {/* Sub-tabs */}
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid rgba(0,0,0,0.08)", paddingBottom: 8, flexShrink: 0 }}>
        {(["preview", "plan", "log", "obsidian"] as DetailTab[]).map(t => (
          <button key={t} onClick={() => setTab(t)} style={TAB_STYLE(tab === t)}>
            {t === "obsidian" ? "Obsidian" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
        {tab === "preview" && <AgentPreview state={state} founderId={founderId} company={company} />}

        {tab === "plan" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {planTask && (
              <div style={{ padding: "10px 14px", borderRadius: 24, background: "rgba(180,205,228,0.10)", border: "1px solid rgba(0,0,0,0.08)" }}>
                <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)", marginBottom: 5 }}>Task instruction</div>
                <p style={{ margin: 0, fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.6 }}>{planTask.instruction}</p>
              </div>
            )}
            {state.result && (
              <div style={{ padding: "10px 14px", borderRadius: 24, background: "rgba(180,205,228,0.10)", border: "1px solid rgba(0,0,0,0.08)" }}>
                <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)", marginBottom: 5 }}>Output</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {Object.entries(state.result).filter(([, v]) => v !== null && v !== undefined).slice(0, 8).map(([k, v]) => (
                    <div key={k} style={{ display: "flex", gap: 8, fontSize: 11 }}>
                      <span style={{ color: "var(--fg-mute)", minWidth: 100, flexShrink: 0 }}>{k.replace(/_/g, " ")}</span>
                      <span style={{ color: "var(--fg-dim)", wordBreak: "break-all" }}>{typeof v === "string" ? v.slice(0, 120) : JSON.stringify(v).slice(0, 80)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {tab === "log" && (
          <div ref={logRef} style={{ display: "flex", flexDirection: "column", gap: 2, maxHeight: 380, overflowY: "auto" }}>
            {state.log.length === 0 && <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>Waiting to start…</span>}
            {state.log.map((entry, i) => (
              <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 10, lineHeight: 1.5, padding: "2px 0" }}>
                <span style={{ fontFamily: "var(--font-jetbrains-mono)", flexShrink: 0, color: "rgba(0,0,0,0.3)", minWidth: 56 }}>
                  {new Date(entry.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                </span>
                <span style={{ color: entry.type === "error" ? "#C0392B" : entry.type === "result" ? "#3D9E5F" : "var(--fg-dim)" }}>{entry.text}</span>
              </div>
            ))}
          </div>
        )}

        {tab === "obsidian" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {obsidianLoading && <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>Loading Obsidian note…</span>}
            {!obsidianLoading && obsidianError && (
              <div style={{ borderRadius: 18, border: "1px solid rgba(192,57,43,0.22)", background: "rgba(192,57,43,0.06)", padding: "12px 14px", fontSize: 12, color: "#C97070", lineHeight: 1.6 }}>
                {obsidianError}
              </div>
            )}
            {!obsidianLoading && !obsidianError && obsidianNote !== null && (
              <pre style={{
                margin: 0,
                padding: "14px 16px",
                borderRadius: 24,
                border: "1px solid rgba(0,0,0,0.08)",
                background: "rgba(180,205,228,0.10)",
                color: "var(--fg-dim)",
                fontSize: 11,
                lineHeight: 1.75,
                fontFamily: "var(--font-jetbrains-mono)",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}>
                {obsidianNote || "This note is empty."}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Sidebar agent list ──────────────────────────────────────────────────────

function AgentSidebar({ agentList, agents, activeAgent, onSelect }: {
  agentList: string[];
  agents: Record<string, AgentState>;
  activeAgent: string;
  onSelect: (a: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {agentList.map(name => {
        const state = agents[name];
        const status = state?.status ?? "waiting";
        const isActive = name === activeAgent;
        const p = state ? pct(state) : 0;
        return (
          <button key={name} onClick={() => onSelect(name)} style={{
            display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 24,
            border: isActive ? "1px solid rgba(180,205,228,0.22)" : "1px solid transparent",
            background: isActive ? "rgba(180,205,228,0.10)" : "transparent",
            cursor: "pointer", textAlign: "left", transition: "background 0.15s",
            boxShadow: isActive ? "0 1px 3px rgba(0,0,0,0.05)" : "none",
          }}>
            <div style={{ position: "relative", width: 28, height: 28, flexShrink: 0 }}>
              <svg viewBox="0 0 28 28" style={{ transform: "rotate(-90deg)", width: 28, height: 28 }}>
                <circle cx="14" cy="14" r="11" fill="none" stroke="rgba(0,0,0,0.1)" strokeWidth="2.5" />
                <circle cx="14" cy="14" r="11" fill="none" stroke={status === "done" ? "#3D9E5F" : status === "running" ? "#2563EB" : status === "error" ? "#C0392B" : "transparent"}
                  strokeWidth="2.5"
                  strokeDasharray={`${2 * Math.PI * 11}`}
                  strokeDashoffset={`${2 * Math.PI * 11 * (1 - p / 100)}`}
                  style={{ transition: "stroke-dashoffset 0.5s" }} />
              </svg>
              <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12 }}>{AGENT_ICONS[name] ?? "🤖"}</span>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 500, color: isActive ? "var(--fg)" : "var(--fg-mute)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {AGENT_LABELS[name] ?? name}
              </div>
              <div style={{ fontSize: 10, color: STATUS_COLOR[status] ?? "rgba(0,0,0,0.25)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{status}</div>
            </div>
            {status === "running" && (
              <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#2563EB", flexShrink: 0 }} className="animate-pulse" />
            )}
          </button>
        );
      })}
    </div>
  );
}

// ── Agent Input Request Modal ───────────────────────────────────────────────

interface InputField {
  name: string;
  label: string;
  type: string;
  required?: boolean;
  hint?: string;
}

interface InputRequest {
  request_id: string;
  title: string;
  fields: InputField[];
}

function AgentInputModal({ sessionId, request, onDone }: {
  sessionId: string;
  request: InputRequest;
  onDone: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    // Validate required fields
    const missing = request.fields.filter(f => f.required && !values[f.name]?.trim());
    if (missing.length > 0) { setError(`Required: ${missing.map(f => f.label).join(", ")}`); return; }
    setSubmitting(true); setError("");
    try {
      const res = await fetch(`${BASE}/input/${sessionId}/${request.request_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: values }),
      });
      if (!res.ok) throw new Error("Submit failed");
      onDone();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to submit");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    // Full-screen overlay
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999,
      background: "rgba(0,0,0,0.6)", backdropFilter: "blur(8px)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 24,
    }}>
      <div style={{
        width: "100%", maxWidth: 520,
        background: "var(--glass)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)",
        border: "1px solid var(--line)", borderRadius: 24,
        boxShadow: "var(--shadow-lg)", overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{ padding: "18px 24px", borderBottom: "1px solid var(--line-2)", display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 20 }}>⚖️</span>
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "var(--fg)", letterSpacing: "-0.02em" }}>{request.title}</h2>
            <p style={{ margin: "3px 0 0", fontSize: 12, color: "var(--fg-mute)" }}>Required to complete your LLC filing — stays in memory only, never stored.</p>
          </div>
        </div>

        {/* Fields */}
        <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 14 }}>
          {request.fields.map(field => (
            <div key={field.name} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <label style={{ fontSize: 12, fontWeight: 500, color: "var(--fg)", display: "flex", alignItems: "center", gap: 6 }}>
                {field.label}
                {field.required && <span style={{ color: "#f87171", fontSize: 10 }}>*</span>}
              </label>
              <input
                type={field.type}
                value={values[field.name] ?? ""}
                onChange={e => setValues(v => ({ ...v, [field.name]: e.target.value }))}
                onKeyDown={e => e.key === "Enter" && submit()}
                className="site-input"
                style={{ padding: "9px 12px", fontSize: 13, fontFamily: field.type === "password" ? "var(--font-mono)" : undefined }}
                autoComplete={field.type === "password" ? "new-password" : field.name}
              />
              {field.hint && <span style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.5 }}>{field.hint}</span>}
            </div>
          ))}

          {error && <p style={{ margin: 0, fontSize: 12, color: "#f87171" }}>{error}</p>}

          <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
            <button
              onClick={submit}
              disabled={submitting}
              className="site-btn site-btn-primary"
              style={{ flex: 1, minHeight: 42, fontSize: 14 }}
            >
              {submitting ? "Submitting…" : "Continue filing →"}
            </button>
          </div>

          <p style={{ margin: 0, fontSize: 10, color: "var(--fg-mute)", textAlign: "center", lineHeight: 1.5 }}>
            🔒 Your SSN and personal info are used only for this filing and never written to disk.
          </p>
        </div>
      </div>
    </div>
  );
}

// ── LLC Filing Modal — live browser stream ───────────────────────────────────

type FilingPhase = "connecting" | "running" | "interaction_needed" | "bot_filling" | "payment_filling" | "done" | "error";

interface FilingFieldOption { value: string; label: string; description?: string; }
interface FilingField { name: string; label: string; type: string; required?: boolean; options?: FilingFieldOption[]; default?: string; price?: string; placeholder?: string; show_if?: string; }

function LLCFilingModal({ founderId, companyName, state, onClose }: {
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
    // Apply defaults for select fields the user didn't touch
    const data = { ...formValues };
    fields.forEach(f => { if (f.type === "select" && !data[f.name] && f.default) data[f.name] = f.default; });
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
            <span style={{ fontSize: 16 }}>⚖️</span>
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
            height: "100%", borderRadius: 999, transition: "width 0.6s",
            width: `${phase === "done" ? 100 : stepPercent}%`,
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


// ── Steer + Ask panels ─────────────────────────────────────────────────────

function SteerPanel({ sessionId, isRunning }: { sessionId: string; isRunning: boolean }) {
  const [msg, setMsg] = useState("");
  const [sent, setSent] = useState(false);
  if (!isRunning) return null;
  const send = async () => {
    if (!msg.trim()) return;
    await fetch(`${BASE}/steer/${sessionId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: msg }) });
    setSent(true); setMsg(""); setTimeout(() => setSent(false), 2000);
  };
  return (
    <LiquidGlass contentStyle={{ padding: "12px 14px" }}>
      <div style={{ fontSize: 11, color: "var(--fg-mute)", marginBottom: 8 }}>Steer agents mid-run</div>
      <div style={{ display: "flex", gap: 8 }}>
        <input value={msg} onChange={e => setMsg(e.target.value)} onKeyDown={e => e.key === "Enter" && send()}
          placeholder="e.g. focus on B2B customers"
          className="site-input"
          style={{ flex: 1, padding: "7px 12px", fontSize: 12 }} />
        <button onClick={send} className="site-btn site-btn-primary" style={{ padding: "0 14px", fontSize: 12 }}>
          {sent ? "Sent" : "Send"}
        </button>
      </div>
    </LiquidGlass>
  );
}

function AskPanel({ sessionId, founderId }: { sessionId: string; founderId: string }) {
  const [msg, setMsg] = useState(""); const [reply, setReply] = useState(""); const [loading, setLoading] = useState(false);
  const ask = async () => {
    if (!msg.trim()) return;
    setLoading(true); setReply("");
    const r = await fetch(`${BASE}/ask`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, founder_id: founderId, question: msg }) });
    const d = await r.json(); setReply(d.answer ?? d.response ?? JSON.stringify(d)); setLoading(false);
  };
  return (
    <LiquidGlass contentStyle={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 11, color: "var(--fg-mute)" }}>Ask about your results</div>
      <div style={{ display: "flex", gap: 8 }}>
        <input value={msg} onChange={e => setMsg(e.target.value)} onKeyDown={e => e.key === "Enter" && ask()}
          placeholder="What are the top competitors?"
          className="site-input"
          style={{ flex: 1, padding: "7px 12px", fontSize: 12 }} />
        <button onClick={ask} className="site-btn site-btn-primary" style={{ padding: "0 14px", fontSize: 12 }}>
          {loading ? "…" : "Ask"}
        </button>
      </div>
      {reply && <div style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.6, padding: "8px 10px", background: "rgba(180,205,228,0.10)", border: "1px solid rgba(180,205,228,0.22)", borderRadius: 12 }}>{reply}</div>}
    </LiquidGlass>
  );
}

// ── Continue panel ──────────────────────────────────────────────────────────

function ContinuePanel({ sessionId, founderId, company }: { sessionId: string; founderId: string; company: string }) {
  const router = useRouter();
  const [instruction, setInstruction] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const SUGGESTIONS = [
    "Update the landing page copy and add a pricing section",
    "Write 5 LinkedIn posts for launch week",
    "Add a blog to the site and write the first post",
    "Build an admin dashboard with user analytics",
    "Create investor outreach emails for 10 seed funds",
    "Add Stripe payments and a subscription tier page",
  ];

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!instruction.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await continueSession(founderId, sessionId, instruction);
      router.push(`/?session=${encodeURIComponent(result.session_id)}&instruction=${encodeURIComponent(instruction)}&founder=${encodeURIComponent(founderId)}&company=${encodeURIComponent(company)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to continue");
      setLoading(false);
    }
  }

  return (
    <LiquidGlass contentStyle={{ padding: "28px 32px", display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span className="site-label">Continue building</span>
        <h3 style={{ fontSize: 16, margin: 0 }}>What do you want to do next?</h3>
      </div>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <textarea
          value={instruction}
          onChange={e => setInstruction(e.target.value)}
          placeholder="Update the landing page, write LinkedIn posts, add Stripe payments, build a dashboard…"
          rows={3}
          className="site-textarea"
          style={{ padding: "12px 14px", fontSize: 14, lineHeight: 1.6, resize: "none" }}
          disabled={loading}
        />
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button type="submit" disabled={loading || !instruction.trim()} className="site-btn site-btn-primary" style={{ padding: "0 22px" }}>
            {loading ? "Launching…" : "Run agents"} <span aria-hidden>→</span>
          </button>
        </div>
        {error && <p style={{ fontSize: 12, color: "#f87171", margin: 0 }}>{error}</p>}
      </form>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {SUGGESTIONS.map(s => (
          <button key={s} type="button" onClick={() => setInstruction(s)} disabled={loading}
            style={{ fontSize: 12, padding: "5px 12px", borderRadius: 999, border: "1px solid var(--line)", background: "transparent", cursor: "pointer", color: "var(--text-2)" }}>
            {s}
          </button>
        ))}
      </div>
    </LiquidGlass>
  );
}

function NewGoalOverlay({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const { user, isSignedIn } = useUser();
  const [companyName, setCompanyName] = useState("");
  const [domain, setDomain] = useState("");
  const [instruction, setInstruction] = useState("");
  const [showStack, setShowStack] = useState(false);
  const [stack, setStack] = useState({ frontend: "Next.js", backend: "FastAPI", database: "Supabase (Postgres)", auth: "Clerk" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!instruction.trim()) return;
    setLoading(true);
    setError(null);
    const parts = [
      companyName.trim() && `Company name: ${companyName.trim()}.`,
      domain.trim() && `Domain: ${domain.trim()}.`,
      showStack && `Tech stack: Frontend=${stack.frontend}, Backend=${stack.backend}, Database=${stack.database}, Auth=${stack.auth}.`,
    ].filter(Boolean);
    const full = parts.length ? `${parts.join(" ")}\n\n${instruction}` : instruction;
    const founderId = user?.id ?? "anon";
    try {
      const result = await submitGoal(founderId, full);
      saveSession({
        sessionId: result.session_id,
        founderId,
        companyName: companyName.trim() || instruction.slice(0, 40),
        instruction,
        startedAt: Date.now(),
        status: "running",
        artifacts: [],
      });
      if (typeof Notification !== "undefined" && Notification.permission === "default") Notification.requestPermission();
      router.push(`/?session=${encodeURIComponent(result.session_id)}&instruction=${encodeURIComponent(instruction)}&founder=${encodeURIComponent(founderId)}&company=${encodeURIComponent(companyName)}`);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit goal");
      setLoading(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 120, display: "grid", placeItems: "center", padding: 24, background: "rgba(5,8,13,0.52)", backdropFilter: "blur(18px)", WebkitBackdropFilter: "blur(18px)" }}>
      <LiquidGlass style={{ width: "min(1120px, 100%)" }} contentStyle={{ padding: "28px 30px", display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
          <div style={{ flex: 1, display: "grid", gap: 5 }}>
            <span className="site-label">New goal</span>
            <h2 style={{ margin: 0, fontSize: 22, letterSpacing: "-0.03em" }}>Launch a new agent run</h2>
            <p style={{ margin: 0, color: "var(--fg-dim)", fontSize: 13, lineHeight: 1.55 }}>
              Describe the product once. Astra will split it into research, build, launch, and handoff lanes.
            </p>
          </div>
          <button type="button" onClick={onClose} className="site-btn site-btn-ghost" style={{ minHeight: 34, padding: "0 13px", fontSize: 12 }}>
            Close
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1.1fr 0.9fr", gap: 12 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label className="site-label">Company</label>
              <input value={companyName} onChange={e => setCompanyName(e.target.value)} className="site-input" style={{ padding: "10px 13px", fontSize: 14 }} placeholder="Astra" disabled={loading} />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label className="site-label">Domain</label>
              <input value={domain} onChange={e => setDomain(e.target.value)} className="site-input" style={{ padding: "10px 13px", fontSize: 14 }} placeholder="astra.ai" disabled={loading} />
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label className="site-label">Goal</label>
            <textarea
              value={instruction}
              onChange={e => setInstruction(e.target.value)}
              placeholder="Build a SaaS for indie hackers to track MRR — landing page, GitHub repo, Supabase backend, Clerk auth, Vercel deploy."
              rows={5}
              disabled={loading}
              className="site-textarea"
              style={{ padding: "13px 14px", fontSize: 14, lineHeight: 1.65, resize: "none" }}
            />
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {STARTER_PROMPTS.map((item) => (
              <button key={item.title} type="button" onClick={() => setInstruction(item.prompt)} disabled={loading}
                style={{ borderRadius: 999, border: "1px solid var(--line)", background: "rgba(255,255,255,0.03)", color: "var(--fg-dim)", padding: "7px 12px", fontSize: 12, cursor: "pointer" }}>
                {item.title}
              </button>
            ))}
          </div>

          <div style={{ border: "1px solid var(--line)", borderRadius: 24, padding: "10px 14px" }}>
            <button type="button" onClick={() => setShowStack(v => !v)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
              <span className="site-label">Tech stack</span>
              <span style={{ fontSize: 10, color: "var(--fg-mute)" }}>{showStack ? "▲" : "▼"}</span>
            </button>
            {showStack && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 14 }}>
                {(Object.entries(STACK_OPTIONS) as [string, string[]][]).map(([key, opts]) => (
                  <div key={key} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <label className="site-label">{key}</label>
                    <select value={stack[key as keyof typeof stack]} onChange={e => setStack(p => ({ ...p, [key]: e.target.value }))} disabled={loading} className="site-input" style={{ padding: "8px 10px", fontSize: 12, background: "linear-gradient(135deg, rgba(255,255,255,0.08), rgba(180,205,228,0.04)), var(--glass-hi)" }}>
                      {opts.map(o => <option key={o} value={o} style={{ background: "#0b0e14" }}>{o}</option>)}
                    </select>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, paddingTop: 4 }}>
            {isSignedIn ? (
              <button type="submit" disabled={loading || !instruction.trim()} className="site-btn site-btn-primary" style={{ padding: "0 24px", fontSize: 14 }}>
                {loading ? "Launching..." : "Launch Astra ->"}
              </button>
            ) : (
              <SignInButton mode="modal">
                <button type="button" className="site-btn site-btn-primary" style={{ padding: "0 24px", fontSize: 14 }}>Sign in to launch -&gt;</button>
              </SignInButton>
            )}
          </div>

          {error && <p style={{ borderRadius: 24, border: "1px solid rgba(220,38,38,0.4)", background: "rgba(127,29,29,0.2)", padding: "10px 14px", fontSize: 13, color: "#fca5a5", margin: 0 }}>{error}</p>}
        </form>
      </LiquidGlass>
    </div>
  );
}

function WorkspaceSidebar({
  title,
  status,
  sessionId,
  onNewGoal,
  onOpenPlan,
}: {
  title: string;
  status: string;
  sessionId: string;
  onNewGoal: () => void;
  onOpenPlan: () => void;
}) {
  const navItemStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 10,
    width: "100%",
    minHeight: 42,
    padding: "0 13px",
    borderRadius: 22,
    border: "1px solid rgba(176,180,186,0.10)",
    background: "rgba(255,255,255,0.025)",
    color: "var(--fg-dim)",
    fontSize: 13,
    textDecoration: "none",
    cursor: "pointer",
  };

  return (
    <LiquidGlass style={{ minWidth: 0 }} contentStyle={{ padding: 14, display: "flex", flexDirection: "column", gap: 14, minHeight: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 4px 10px" }}>
        <div style={{ width: 28, height: 28, borderRadius: 10, display: "grid", placeItems: "center", background: "rgba(168,172,178,0.92)", color: "rgba(10,14,22,0.92)", fontWeight: 700, fontSize: 13, flexShrink: 0 }}>A</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--fg)", whiteSpace: "nowrap" }}>Astra</div>
          <div style={{ fontSize: 10, color: "var(--fg-mute)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{status}</div>
        </div>
      </div>

      <button type="button" onClick={onNewGoal} className="site-btn site-btn-primary" style={{ width: "100%", minHeight: 42, justifyContent: "flex-start", padding: "0 14px", fontSize: 13 }}>
        <span aria-hidden="true">＋</span>
        New goal
      </button>

      <div style={{ display: "grid", gap: 8 }}>
        <a href="#current-run" style={{ ...navItemStyle, color: "var(--fg)" }}>
          <span aria-hidden="true">●</span>
          Current run
        </a>
        <button type="button" onClick={onOpenPlan} style={navItemStyle}>
          <span aria-hidden="true">▣</span>
          Plan
        </button>
        <Link href="/brain" style={navItemStyle}>
          <span aria-hidden="true">◎</span>
          Company brain
        </Link>
        <Link href="/settings" style={navItemStyle}>
          <span aria-hidden="true">⚙</span>
          Account settings
        </Link>
        <Link href="/integrations" style={navItemStyle}>
          <span aria-hidden="true">⌘</span>
          Integrations
        </Link>
        <Link href="/payments" style={navItemStyle}>
          <span aria-hidden="true">$</span>
          Payments
        </Link>
        <a href="https://astracreates.com/" style={navItemStyle}>
          <span aria-hidden="true">↗</span>
          About
        </a>
      </div>

      <SessionHistory currentSessionId={sessionId} />

      <div style={{ display: "grid", gap: 10 }}>
        <div style={{ padding: "12px 13px", borderRadius: 22, border: "1px solid rgba(176,180,186,0.10)", background: "rgba(255,255,255,0.025)", display: "grid", gap: 5 }}>
          <span style={{ fontSize: 10, color: "var(--fg-mute)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Session</span>
          <span style={{ fontSize: 12, color: "var(--fg)", lineHeight: 1.45, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</span>
          <span style={{ fontSize: 10, color: "var(--fg-mute)", fontFamily: "var(--font-jetbrains-mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sessionId || "new draft"}</span>
        </div>
        <ThemeToggle />
      </div>
    </LiquidGlass>
  );
}

function SessionHistory({ currentSessionId }: { currentSessionId: string }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const sessions = useSyncExternalStore(subscribeSessions, getSessionSnapshot, getSessionSnapshot);
  const router = useRouter();
  if (!mounted || sessions.length === 0) return null;
  const statusDot = (s: SessionRecord["status"]) =>
    s === "done" ? "#3D9E5F" : s === "running" ? "#2563EB" : "#C0392B";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 4px" }}>
        <span style={{ fontSize: 10, color: "var(--fg-mute)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Recent</span>
        <button
          onClick={() => { if (confirm("Clear all sessions?")) { clearAllSessions(); router.push("/"); } }}
          style={{ fontSize: 10, color: "var(--fg-mute)", background: "none", border: "none", cursor: "pointer", padding: "2px 6px", borderRadius: 4 }}
        >Clear all</button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 220, overflowY: "auto" }}>
        {sessions.map(s => (
          <div key={s.sessionId} style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", borderRadius: 12, background: s.sessionId === currentSessionId ? "rgba(255,255,255,0.06)" : "rgba(255,255,255,0.02)", border: `1px solid ${s.sessionId === currentSessionId ? "rgba(176,180,186,0.18)" : "rgba(176,180,186,0.08)"}`, cursor: "pointer" }}
            onClick={() => router.push(`/?session=${s.sessionId}&instruction=${encodeURIComponent(s.instruction)}&founder=${encodeURIComponent(s.founderId)}&company=${encodeURIComponent(s.companyName)}`)}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: statusDot(s.status), flexShrink: 0 }} />
            <span style={{ flex: 1, fontSize: 11, color: "var(--fg-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>{s.companyName || s.instruction.slice(0, 30)}</span>
            <button
              onClick={e => { e.stopPropagation(); deleteSession(s.sessionId); if (s.sessionId === currentSessionId) router.push("/"); }}
              style={{ fontSize: 11, color: "var(--fg-mute)", background: "none", border: "none", cursor: "pointer", padding: "0 2px", lineHeight: 1, flexShrink: 0 }}
              title="Delete session"
            >✕</button>
          </div>
        ))}
      </div>
    </div>
  );
}

interface PlanNode {
  id: string;
  agent: string;
  title: string;
  description: string;
  steps: string[];
  depends_on: string[];
  estimated_time?: string;
}

function PlanTreeNode({
  node,
  agentStatus,
  depth,
  onEdit,
}: {
  node: PlanNode;
  agentStatus: "waiting" | "running" | "done" | "error" | undefined;
  depth: number;
  onEdit: (id: string, field: "title" | "description" | "steps", value: string | string[]) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const [editingStep, setEditingStep] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [editingDesc, setEditingDesc] = useState(false);

  const statusColor = agentStatus === "done" ? "#3D9E5F" : agentStatus === "running" ? "#2563EB" : agentStatus === "error" ? "#C0392B" : "rgba(176,180,186,0.3)";
  const statusBg = agentStatus === "done" ? "rgba(61,158,95,0.12)" : agentStatus === "running" ? "rgba(37,99,235,0.12)" : "rgba(255,255,255,0.03)";
  const icon = AGENT_ICONS[node.agent] ?? "◆";
  const completedSteps = agentStatus === "done" ? node.steps.length : agentStatus === "running" ? Math.ceil(node.steps.length * 0.5) : 0;

  return (
    <div style={{ marginLeft: depth * 20, position: "relative" }}>
      {depth > 0 && (
        <div style={{ position: "absolute", left: -16, top: 20, width: 12, height: 1, background: "rgba(176,180,186,0.2)" }} />
      )}
      <div style={{ borderRadius: 14, border: `1px solid ${statusColor}`, background: statusBg, overflow: "hidden", marginBottom: 8 }}>
        {/* Node header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", cursor: "pointer" }} onClick={() => setExpanded(e => !e)}>
          <span style={{ fontSize: 16, flexShrink: 0 }}>{icon}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            {editingTitle ? (
              <input
                autoFocus
                defaultValue={node.title}
                style={{ width: "100%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(180,205,228,0.22)", borderRadius: 6, padding: "2px 8px", fontSize: 13, fontWeight: 600, color: "var(--fg)" }}
                onBlur={e => { onEdit(node.id, "title", e.target.value); setEditingTitle(false); }}
                onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                onClick={e => e.stopPropagation()}
              />
            ) : (
              <span
                style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}
                onDoubleClick={e => { e.stopPropagation(); setEditingTitle(true); }}
              >{node.title}</span>
            )}
            <span style={{ fontSize: 10, color: "var(--fg-mute)", marginLeft: 8, textTransform: "uppercase", letterSpacing: "0.08em" }}>{AGENT_LABELS[node.agent] ?? node.agent}</span>
          </div>
          {node.estimated_time && <span style={{ fontSize: 10, color: "var(--fg-mute)", flexShrink: 0 }}>{node.estimated_time}</span>}
          {/* Progress bar */}
          <div style={{ width: 60, height: 3, borderRadius: 2, background: "rgba(255,255,255,0.08)", flexShrink: 0, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${node.steps.length ? (completedSteps / node.steps.length) * 100 : 0}%`, background: statusColor, borderRadius: 2, transition: "width 0.4s" }} />
          </div>
          <span style={{ fontSize: 12, color: "var(--fg-mute)", flexShrink: 0 }}>{expanded ? "▾" : "▸"}</span>
        </div>

        {expanded && (
          <div style={{ borderTop: "1px solid rgba(176,180,186,0.08)", padding: "10px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
            {/* Description */}
            {editingDesc ? (
              <textarea
                autoFocus
                defaultValue={node.description}
                rows={2}
                style={{ width: "100%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(180,205,228,0.22)", borderRadius: 6, padding: "6px 8px", fontSize: 12, color: "var(--fg-dim)", resize: "vertical" }}
                onBlur={e => { onEdit(node.id, "description", e.target.value); setEditingDesc(false); }}
              />
            ) : (
              <p style={{ margin: 0, fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.55, cursor: "text" }} onDoubleClick={() => setEditingDesc(true)}>{node.description}</p>
            )}

            {/* Steps */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {node.steps.map((step, i) => (
                <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                  <div style={{ width: 16, height: 16, borderRadius: 4, border: `1.5px solid ${i < completedSteps ? statusColor : "rgba(176,180,186,0.25)"}`, background: i < completedSteps ? statusColor : "transparent", flexShrink: 0, marginTop: 1, display: "grid", placeItems: "center" }}>
                    {i < completedSteps && <span style={{ fontSize: 9, color: "#fff" }}>✓</span>}
                  </div>
                  {editingStep === i ? (
                    <input
                      autoFocus
                      defaultValue={step}
                      style={{ flex: 1, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(180,205,228,0.22)", borderRadius: 4, padding: "2px 6px", fontSize: 11, color: "var(--fg)" }}
                      onBlur={e => {
                        const newSteps = [...node.steps];
                        newSteps[i] = e.target.value;
                        onEdit(node.id, "steps", newSteps);
                        setEditingStep(null);
                      }}
                      onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                    />
                  ) : (
                    <span style={{ fontSize: 11, color: i < completedSteps ? "var(--fg-mute)" : "var(--fg-dim)", lineHeight: 1.5, textDecoration: i < completedSteps ? "line-through" : "none", cursor: "text" }} onDoubleClick={() => setEditingStep(i)}>{step}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PlanOverlay({
  open,
  onClose,
  title,
  planTasks,
  detailedNodes,
  agents,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  planTasks: AgentTask[];
  detailedNodes: PlanNode[];
  agents: Record<string, AgentState>;
}) {
  const [nodes, setNodes] = useState<PlanNode[]>([]);

  useEffect(() => {
    if (detailedNodes.length > 0) setNodes(detailedNodes);
  }, [detailedNodes]);

  const handleEdit = (id: string, field: "title" | "description" | "steps", value: string | string[]) => {
    setNodes(prev => prev.map(n => n.id === id ? { ...n, [field]: value } : n));
  };

  if (!open) return null;

  const totalSteps = nodes.reduce((s, n) => s + n.steps.length, 0);
  const doneSteps = nodes.reduce((s, n) => {
    const st = agents[n.agent]?.status;
    return s + (st === "done" ? n.steps.length : st === "running" ? Math.ceil(n.steps.length * 0.5) : 0);
  }, 0);
  const overallPct = totalSteps ? Math.round((doneSteps / totalSteps) * 100) : 0;
  const doneCount = nodes.filter(n => agents[n.agent]?.status === "done").length;

  // Build dependency tree: group by depth (nodes with no deps first, then their dependents)
  const roots = nodes.filter(n => !n.depends_on?.length);
  const rest = nodes.filter(n => n.depends_on?.length > 0);

  const renderNodes = (subset: PlanNode[], depth: number) =>
    subset.map(n => (
      <div key={n.id}>
        <PlanTreeNode node={n} agentStatus={agents[n.agent]?.status} depth={depth} onEdit={handleEdit} />
        {renderNodes(rest.filter(r => r.depends_on?.includes(n.id)), depth + 1)}
      </div>
    ));

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 130, display: "grid", placeItems: "center", padding: 24, background: "rgba(5,8,13,0.56)", backdropFilter: "blur(18px)", WebkitBackdropFilter: "blur(18px)" }}>
      <LiquidGlass style={{ width: "min(1480px, 100%)" }} contentStyle={{ padding: "28px 32px", height: "min(820px, calc(100vh - 48px))", display: "flex", flexDirection: "column", gap: 18 }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: 18 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <span className="site-label">Execution Plan</span>
            <h2 style={{ margin: "4px 0 0", fontSize: "clamp(20px, 2.4vw, 30px)", lineHeight: 1.1, letterSpacing: "-0.04em", overflowWrap: "anywhere" }}>{title || "Launch plan"}</h2>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
            {nodes.length > 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ width: 120, height: 4, borderRadius: 2, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${overallPct}%`, background: "#2563EB", borderRadius: 2, transition: "width 0.4s" }} />
                </div>
                <span style={{ fontSize: 11, color: "var(--fg-mute)", fontFamily: "var(--font-jetbrains-mono)" }}>{doneCount}/{nodes.length} agents · {overallPct}%</span>
              </div>
            )}
            <button type="button" onClick={onClose} className="site-btn site-btn-ghost" style={{ minHeight: 32, padding: "0 14px", fontSize: 12 }}>Close</button>
          </div>
        </div>

        {/* Tree or loading */}
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", paddingRight: 4 }}>
          {nodes.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
              {renderNodes(roots, 0)}
              {renderNodes(rest.filter(r => !nodes.some(n => n.id !== r.id && r.depends_on?.includes(n.id) === false) && roots.every(root => !r.depends_on?.includes(root.id))), 0)}
            </div>
          ) : planTasks.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ padding: "12px 16px", borderRadius: 12, background: "rgba(37,99,235,0.08)", border: "1px solid rgba(37,99,235,0.2)", fontSize: 12, color: "var(--fg-dim)" }}>
                ⏳ Detailed plan generates after research completes…
              </div>
              {planTasks.map((task, i) => (
                <div key={task.id} style={{ display: "flex", gap: 12, alignItems: "flex-start", padding: "10px 14px", borderRadius: 12, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)" }}>
                  <span style={{ width: 26, height: 26, borderRadius: 999, display: "grid", placeItems: "center", background: "rgba(255,255,255,0.05)", fontSize: 10, color: "var(--fg-mute)", flexShrink: 0 }}>{i + 1}</span>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>{AGENT_LABELS[task.agent] ?? task.agent}</div>
                    <div style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.5, marginTop: 2 }}>{task.instruction}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ display: "grid", placeItems: "center", height: "100%", color: "var(--fg-mute)", fontSize: 13 }}>
              Plan will appear here once the session starts.
            </div>
          )}
        </div>

        <div style={{ fontSize: 10, color: "var(--fg-mute)", borderTop: "1px solid rgba(176,180,186,0.08)", paddingTop: 10 }}>
          Double-click any title, description, or step to edit · Progress updates live as agents complete
        </div>
      </LiquidGlass>
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────────────

export function GoalWorkspace({
  sessionId,
  instruction = "",
  founderId = "founder_001",
  company = "",
  startNew = false,
}: {
  sessionId: string;
  instruction?: string;
  founderId?: string;
  company?: string;
  startNew?: boolean;
}) {

  // ── Persistent session cache ──────────────────────────────────────────────
  const CACHE_KEY = `astra_session_${sessionId}`;

  const saveCache = useCallback((a: Record<string, AgentState>, p: AgentTask[], d: boolean, cn?: string) => {
    if (!sessionId) return;
    try { localStorage.setItem(CACHE_KEY, JSON.stringify({ agents: a, planTasks: p, done: d, autoCompanyName: cn })); } catch {}
  }, [CACHE_KEY, sessionId]);

  // Always start with empty state to avoid SSR/client hydration mismatch;
  // load localStorage cache in useEffect after mount.
  const [agents, setAgents] = useState<Record<string, AgentState>>({});
  const [planTasks, setPlanTasks] = useState<AgentTask[]>([]);
  const [activeAgent, setActiveAgent] = useState<string>("");
  const [expandedGoal, setExpandedGoal] = useState<string>("");
  const [autoCompanyName, setAutoCompanyName] = useState<string>("");
  const [done, setDone] = useState(false);
  const [inputRequest, setInputRequest] = useState<InputRequest | null>(null);

  // Restore from cache after first render (client-only)
  useEffect(() => {
    if (!sessionId) return;
    try {
      const raw = localStorage.getItem(CACHE_KEY);
      if (!raw) return;
      const cached = JSON.parse(raw) as { agents: Record<string, AgentState>; planTasks: AgentTask[]; done: boolean; autoCompanyName?: string };
      const firstAgent = cached.planTasks?.[0]?.agent ?? Object.keys(cached.agents ?? {})[0] ?? "";
      queueMicrotask(() => {
        if (cached.agents && Object.keys(cached.agents).length > 0) {
          // Agents stuck "running" after a refresh will never get done — downgrade to "waiting"
          const fixedAgents: Record<string, AgentState> = {};
          for (const [k, a] of Object.entries(cached.agents)) {
            fixedAgents[k] = a.status === "running" ? { ...a, status: "waiting" } : a;
          }
          setAgents(fixedAgents);
        }
        if (cached.planTasks?.length > 0) setPlanTasks(cached.planTasks);
        if (cached.done) setDone(true);
        if (cached.autoCompanyName) setAutoCompanyName(cached.autoCompanyName);
        if (firstAgent) setActiveAgent(firstAgent);
      });
    } catch {}
  }, [CACHE_KEY, sessionId]);
  const [newGoalOpen, setNewGoalOpen] = useState(startNew || !sessionId);
  const [planOpen, setPlanOpen] = useState(false);
  const [detailedNodes, setDetailedNodes] = useState<PlanNode[]>([]);
  const [pendingDetailedNodes, setPendingDetailedNodes] = useState<PlanNode[]>([]);
  const [nonResearchStarted, setNonResearchStarted] = useState(false);
  const nonResearchStartedRef = useRef(false);
  const pendingDetailedNodesRef = useRef<PlanNode[]>([]);
  useEffect(() => { nonResearchStartedRef.current = nonResearchStarted; }, [nonResearchStarted]);
  useEffect(() => { pendingDetailedNodesRef.current = pendingDetailedNodes; }, [pendingDetailedNodes]);
  useEffect(() => {
    if (startNew || !sessionId) queueMicrotask(() => setNewGoalOpen(true));
  }, [startNew, sessionId]);
  const [error, setError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const everConnected = useRef(false);
  const notified = useRef(false);
  const errorCount = useRef(0);

  // Persist to localStorage whenever state changes
  useEffect(() => { saveCache(agents, planTasks, done, autoCompanyName); }, [agents, planTasks, done, autoCompanyName, saveCache]);

  useEffect(() => {
    if (!sessionId || sessionId === "undefined") return;
    const es = streamGoal(sessionId);
    es.onopen = () => { setConnected(true); setReconnecting(false); errorCount.current = 0; everConnected.current = true; };
    es.onerror = () => {
      setConnected(false); errorCount.current += 1;
      if (errorCount.current >= 5) setError(everConnected.current ? "Connection lost — refresh to reconnect." : "Could not connect. Is the backend running?");
      else setReconnecting(true);
    };

    es.onmessage = (e) => {
      const event = JSON.parse(e.data);
      if (event.type === "ping" || event.type === "founder_steer") return;
      if (event.type === "agent_input_request") {
        setInputRequest({ request_id: event.request_id, title: event.title, fields: event.fields });
        return;
      }
      if (event.type === "agent_input_received") {
        setInputRequest(null);
        return;
      }
      if (event.type === "detailed_plan") {
        const nodes = event.nodes ?? [];
        if (nonResearchStartedRef.current) setDetailedNodes(nodes);
        else setPendingDetailedNodes(nodes);
        return;
      }
      if (event.type === "goal_expanded") { setExpandedGoal(event.expanded ?? ""); return; }
      if (event.type === "company_name") { setAutoCompanyName(event.name ?? ""); return; }
      if (event.type === "session_expired") { setError("Session expired — backend was restarted. Run a new goal."); es.close(); return; }

      setAgents((prev) => {
        const next = { ...prev };
        const SEARCH_TOOLS = new Set(["web_search", "search_and_read", "news_search", "fetch_page", "patent_search", "search_and_fetch", "fetch_and_read", "research_papers"]);

        if (event.type === "plan_done") {
          // Merge into existing planTasks — second plan_done only carries non-research agents
          setPlanTasks(prev => {
            const incomingAgents = new Set(event.tasks.map((t: AgentTask) => t.agent));
            const kept = prev.filter(t => !incomingAgents.has(t.agent));
            return [...kept, ...event.tasks];
          });
          for (const t of event.tasks) {
            const existing = next[t.agent];
            // Don't reset agents already running or done
            if (existing && existing.status !== "waiting") continue;
            next[t.agent] = { task_id: t.id, agent: t.agent, instruction: t.instruction, status: "waiting", currentAction: null, currentTool: null, reasoning: null, result: null, log: [], visitedUrls: [], commits: [] };
          }
          if (!activeAgent && event.tasks.length > 0) setActiveAgent(event.tasks[0].agent);
          return next;
        }

        const agent = event.agent;
        if (!agent) return next;

        const cur: AgentState = next[agent] ?? { task_id: "", agent, instruction: "", status: "waiting", currentAction: null, currentTool: null, reasoning: null, result: null, log: [], visitedUrls: [], commits: [] };
        const addLog = (type: string, text: string): LogEntry[] => [...cur.log, { ts: Date.now(), type, text }];

        if (event.type === "agent_start") {
          if (!agent.startsWith("research")) {
            setNonResearchStarted(true);
            if (pendingDetailedNodesRef.current.length > 0) {
              setDetailedNodes(pendingDetailedNodesRef.current);
              setPendingDetailedNodes([]);
            }
          }
          setActiveAgent(agent);
          next[agent] = { ...cur, status: "running", instruction: event.instruction ?? cur.instruction, task_id: event.task_id ?? cur.task_id, log: addLog("info", "Started") };
        } else if (event.type === "agent_action") {
          const rawArgs = event.args;
          const argsStr = typeof rawArgs === "string" ? rawArgs : (rawArgs?.query ?? rawArgs?.url ?? null);
          const isFetch = event.tool === "fetch_and_read" || event.tool === "fetch_page";
          const urlArg = isFetch ? (rawArgs?.url ?? argsStr ?? "") : "";
          const text = argsStr && event.tool && SEARCH_TOOLS.has(event.tool)
            ? `${event.tool.replace(/_/g, " ")}: "${String(argsStr).slice(0, 80)}"` : event.tool ?? event.action;
          next[agent] = {
            ...cur,
            currentAction: event.action, currentTool: event.tool ?? null, reasoning: event.reasoning ?? null,
            currentUrl: urlArg || cur.currentUrl,
            log: addLog("action", text),
          };
        } else if (event.type === "agent_action_result") {
          const ok = !event.result?.error;
          let text: string;
          let newUrl: string | undefined;
          if (!ok) {
            text = `✗ ${event.tool}: ${event.result?.error ?? "failed"}`;
          } else if (event.tool === "generate_landing_page_html" && typeof event.result === "string") {
            text = event.result.includes("astra-fallback-template")
              ? "⚠ generate_landing_page_html used fallback template"
              : "✓ generate_landing_page_html produced custom HTML";
          } else if (SEARCH_TOOLS.has(event.tool)) {
            const resultStr = typeof event.result === "string" ? event.result : JSON.stringify(event.result ?? "");
            const urlMatch = resultStr.match(/https?:\/\/[^\s"')\]]+/);
            newUrl = urlMatch?.[0]?.replace(/[.,;]+$/, "");
            text = newUrl ? `✓ Read ${newUrl.slice(0, 70)}…` : `✓ ${resultStr.slice(0, 80).replace(/\n/g, " ")}`;
          } else {
            text = `✓ ${TOOL_DESCRIPTIONS[event.tool] ?? event.tool ?? "Done"}`;
          }
          const newVisited = newUrl ? [...(cur.visitedUrls ?? []), newUrl] : cur.visitedUrls;
          const newCommit = event.result?.commit ?? event.result?.commits;
          const newCommits = newCommit
            ? [...(cur.commits ?? []), ...(Array.isArray(newCommit) ? newCommit : [String(newCommit)])]
            : cur.commits;
          // Capture files from run_mvp_loop result
          const newFiles = Array.isArray(event.result?.files_preview) ? event.result.files_preview as string[] : cur.filesPreview;
          const newFilesCount = (event.result?.files_in_repo as number) ?? cur.filesCount;
          // Capture ad images from generate_ad_image tool result
          let newAdImages = cur.adImages;
          const eventImageUrl = (event.result?.url as string | undefined) ?? (event.result?.image_url as string | undefined);
          if (event.tool === "generate_ad_image" && ok && (eventImageUrl || event.result?.base64)) {
            const img = { url: eventImageUrl, base64: event.result.base64 as string | undefined, prompt: event.result.prompt as string | undefined };
            newAdImages = [...(cur.adImages ?? []), img];
          }
          next[agent] = { ...cur, log: addLog(ok ? "result" : "error", text), visitedUrls: newVisited, currentUrl: newUrl ?? cur.currentUrl, commits: newCommits, filesPreview: newFiles, filesCount: newFilesCount, adImages: newAdImages };
        } else if (event.type === "agent_thinking") {
          next[agent] = { ...cur, log: addLog("info", `Thinking… (step ${event.iteration})`) };
        } else if (event.type === "agent_done") {
          const result = event.result ?? {};
          const previewUrl = (result.url ?? result.deployment_url ?? result.project_url ?? result.github_url) as string | undefined;
          // Extract any ad images embedded in the final result (in case tool_result events were missed)
          const doneAdImages = extractAdImagesFromResult(result);
          const mergedAdImages = doneAdImages.length > 0
            ? [...(cur.adImages ?? []), ...doneAdImages].filter((img, i, arr) =>
                arr.findIndex(x => (x.url && x.url === img.url) || (x.base64 && x.base64 === img.base64)) === i)
            : cur.adImages;
          next[agent] = {
            ...cur,
            status: "done",
            currentAction: null,
            currentTool: null,
            result,
            previewUrl,
            adImages: mergedAdImages,
            webQualityError: (result.web_quality_error as string | undefined) ?? cur.webQualityError,
            log: addLog("result", "Complete"),
          };
        } else if (event.type === "agent_error") {
          const qualityError = typeof event.error === "string" && event.error.toLowerCase().includes("fallback template")
            ? "fallback_template_persisted_after_retries"
            : cur.webQualityError;
          next[agent] = { ...cur, status: "error", webQualityError: qualityError, log: addLog("error", event.error ?? "Error") };
        } else if (event.type === "mirror_verdict") {
          next[agent] = { ...cur, mirrorVerdict: event.verdict, mirrorCritique: event.critique };
        } else if (event.type === "goal_done") {
          const results = event.results as Record<string, unknown> | undefined;
          if (results && typeof results === "object") {
            const byAgent: Record<string, Record<string, unknown>> = {};
            for (const [resultKey, value] of Object.entries(results)) {
              if (!value || typeof value !== "object") continue;
              const obj = value as Record<string, unknown>;
              const candidateAgent = typeof obj.agent === "string" ? obj.agent : null;
              if (candidateAgent) {
                byAgent[candidateAgent] = obj;
                continue;
              }
              // Orchestrator goal_done is keyed by task id in many paths.
              // Backfill agent mapping using the live task_id registry.
              const agentByTaskId = Object.values(next).find(s => s.task_id === resultKey)?.agent;
              if (agentByTaskId) byAgent[agentByTaskId] = obj;
            }
            for (const [agentName, resultObj] of Object.entries(byAgent)) {
              const curState = next[agentName] ?? {
                task_id: "",
                agent: agentName,
                instruction: "",
                status: "waiting" as const,
                currentAction: null,
                currentTool: null,
                reasoning: null,
                result: null,
                log: [],
                visitedUrls: [],
                commits: [],
              };
              const doneAdImages = extractAdImagesFromResult(resultObj);
              next[agentName] = {
                ...curState,
                status: "done",
                currentAction: null,
                currentTool: null,
                result: (curState.result ?? resultObj) as Record<string, unknown>,
                previewUrl: (resultObj.url ?? resultObj.deployment_url ?? resultObj.project_url) as string | undefined,
                adImages: doneAdImages.length ? doneAdImages : curState.adImages,
                filesPreview: Array.isArray(resultObj.files_preview) ? (resultObj.files_preview as string[]) : curState.filesPreview,
                filesCount: (resultObj.files_in_repo as number | undefined) ?? curState.filesCount,
              };
            }
          }
          setDone(true);
        }
        else if (event.type === "goal_error") { setError(event.error ?? "Unknown error"); }

        return next;
      });
    };
    return () => es.close();
  }, [sessionId]);

  useEffect(() => {
    if (!done || notified.current) return;
    notified.current = true;
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      new Notification("Astra — goal complete", { body: "Your company is live.", icon: "/favicon.ico" });
    }
  }, [done, sessionId]);

  const PAIR_MAP: Record<string, string> = {};
  // Also include agents that ran but aren't in planTasks (e.g. cached sessions with old planTasks)
  const agentsWithData = Object.keys(agents).filter(a => agents[a].status !== "waiting" || agents[a].log.length > 0);
  const rawAgentList = planTasks.length > 0
    ? sortAgentNamesByOrder([...new Set([...planTasks.map(t => t.agent), ...agentsWithData])])
    : AGENT_ORDER;
  const agentList = [...new Set(rawAgentList.map(a => PAIR_MAP[a] ?? a))];

  // Merge paired agent state: combine logs, urls, pick worst/best status
  function mergeAgentPair(base: string, agents: Record<string, AgentState>): AgentState {
    const pair = base + "_2";
    const a = agents[base];
    const b = agents[pair];
    if (!b) return a ?? { task_id: "", agent: base, instruction: "", status: "waiting", currentAction: null, currentTool: null, reasoning: null, result: null, log: [], visitedUrls: [], commits: [] };
    if (!a) return { ...b, agent: base };
    const statusRank = (s: AgentState["status"]) => s === "running" ? 3 : s === "done" ? 2 : s === "error" ? 1 : 0;
    const mergedStatus: AgentState["status"] = statusRank(a.status) >= statusRank(b.status) ? a.status : b.status;
    const mergedLog = [...(a.log ?? []), ...(b.log ?? [])].sort((x, y) => x.ts - y.ts);
    const mergedUrls = [...new Set([...(a.visitedUrls ?? []), ...(b.visitedUrls ?? [])])];
    const mergedCommits = [...new Set([...(a.commits ?? []), ...(b.commits ?? [])])];
    const activeTool = a.currentTool ?? b.currentTool;
    const activeAction = a.currentAction ?? b.currentAction;
    const activeUrl = a.currentUrl ?? b.currentUrl;
    const mergedResult = a.result || b.result ? { ...(b.result ?? {}), ...(a.result ?? {}) } : null;
    const mergedAdImages = [...(a.adImages ?? []), ...(b.adImages ?? [])];
    return { ...a, status: mergedStatus, log: mergedLog, visitedUrls: mergedUrls, commits: mergedCommits, currentTool: activeTool, currentAction: activeAction, currentUrl: activeUrl, result: mergedResult, adImages: mergedAdImages.length ? mergedAdImages : undefined };
  }

  const visibleAgents: Record<string, AgentState> = {};
  for (const a of agentList) {
    visibleAgents[a] = mergeAgentPair(a, agents);
  }

  const doneCount = Object.values(visibleAgents).filter(a => a.status === "done").length;
  const total = agentList.length;

  const selected = (PAIR_MAP[activeAgent] ?? activeAgent) || agentList[0] || "";
  const selectedState = visibleAgents[selected];
  const selectedPlanTask = planTasks.find(t => t.agent === selected);
  const title = company || instruction.slice(0, 48) || "Astra";
  const runningCount = Object.values(visibleAgents).filter(a => a.status === "running").length;
  const failedCount = Object.values(visibleAgents).filter(a => a.status === "error").length;
  const totalVisitedUrls = Object.values(visibleAgents).reduce((sum, a) => sum + (a.visitedUrls?.length ?? 0), 0);
  const totalCommits = Object.values(visibleAgents).reduce((sum, a) => sum + (a.commits?.length ?? 0), 0);
  const completedAgents = agentList.filter(a => visibleAgents[a]?.status === "done");
  const activeAgents = agentList.filter(a => visibleAgents[a]?.status === "running");
  const completedArtifacts = agentList
    .map((agent) => ({ agent, state: visibleAgents[agent] }))
    .filter(({ state }) => state?.status === "done")
    .map(({ agent, state }) => ({
      agent,
      label: AGENT_LABELS[agent] ?? agent,
      summary: summarizeResult(state),
    }))
    .slice(0, 4);
  const statusText = !sessionId ? "ready" : done ? "complete" : error ? "error" : reconnecting ? "reconnecting..." : connected ? "running" : "connecting";

  return (
    <div className="astra-app-layout" style={{ width: "100%", maxWidth: 1900, margin: "0 auto", display: "grid", gridTemplateColumns: "minmax(190px, 220px) minmax(0, 1fr)", gap: 24, alignItems: "stretch" }}>
      <NewGoalOverlay open={newGoalOpen} onClose={() => setNewGoalOpen(false)} />
      <PlanOverlay open={planOpen} onClose={() => setPlanOpen(false)} title={title} planTasks={planTasks} detailedNodes={detailedNodes} agents={agents} />
      <aside className="astra-workspace-sidebar" style={{ minWidth: 0, alignSelf: "start" }}>
        <WorkspaceSidebar title={title} status={statusText} sessionId={sessionId} onNewGoal={() => setNewGoalOpen(true)} onOpenPlan={() => setPlanOpen(true)} />
      </aside>
      <div id="current-run" className="goal-workspace" style={{
        width: "100%",
        minWidth: 0,
        minHeight: "calc(100vh - clamp(72px, 10vw, 168px))",
        display: "flex",
        flexDirection: "column",
        gap: 24,
        justifyContent: "center",
      }}>
      {/* Header */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: "var(--fg)", margin: 0 }}>{title}</h1>
          <span style={{
            fontSize: 11, letterSpacing: "0.06em", padding: "3px 10px", borderRadius: 999,
            color: done ? "#3D9E5F" : error ? "#C0392B" : reconnecting ? "#B45309" : connected ? "#2563EB" : "var(--fg-mute)",
            background: done ? "rgba(61,158,95,0.08)" : error ? "rgba(192,57,43,0.08)" : reconnecting ? "rgba(180,83,9,0.08)" : connected ? "rgba(37,99,235,0.08)" : "rgba(0,0,0,0.04)",
            border: `1px solid ${done ? "rgba(61,158,95,0.22)" : error ? "rgba(192,57,43,0.22)" : reconnecting ? "rgba(180,83,9,0.22)" : connected ? "rgba(37,99,235,0.22)" : "rgba(0,0,0,0.1)"}`,
          }}>
            {statusText}
          </span>
          {sessionId && <span style={{ fontSize: 11, color: "var(--fg-mute)", fontFamily: "var(--font-jetbrains-mono)" }}>{sessionId}</span>}
        </div>
        {autoCompanyName && (
          <span style={{ fontSize: 11, fontWeight: 600, color: "var(--fg-dim)", letterSpacing: "0.04em", textTransform: "uppercase", fontFamily: "var(--font-jetbrains-mono)" }}>{autoCompanyName}</span>
        )}
        {expandedGoal && (
          <p style={{ margin: 0, fontSize: 12, color: "var(--fg-mute)", lineHeight: 1.6, maxWidth: 820 }}>{expandedGoal}</p>
        )}
        {total > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ flex: 1, height: 3, borderRadius: 999, background: "rgba(0,0,0,0.08)", overflow: "hidden" }}>
              <div style={{ height: "100%", borderRadius: 999, transition: "width 0.7s", width: `${(doneCount / total) * 100}%`, background: done ? "#3D9E5F" : "#2563EB" }} />
            </div>
            <span style={{ fontSize: 11, color: "var(--fg-dim)", flexShrink: 0, fontFamily: "var(--font-jetbrains-mono)" }}>{doneCount}/{total}</span>
          </div>
        )}
        {total === 0 && connected && !error && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--fg-mute)" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#2563EB" }} className="animate-pulse" />
            Planner building task graph…
          </div>
        )}
        {error && <p style={{ borderRadius: 8, border: "1px solid rgba(192,57,43,0.25)", background: "rgba(192,57,43,0.06)", padding: "8px 14px", fontSize: 12, color: "#C0392B", margin: 0 }}>{error}</p>}
      </div>

      {/* Main layout: sidebar + detail */}
      {agentList.length > 0 && (
        <div className="goal-workspace-grid" style={{ display: "grid", gridTemplateColumns: "minmax(260px, 340px) minmax(0, 1fr)", gap: 22, alignItems: "stretch" }}>
          {/* Agent sidebar */}
          <LiquidGlass style={{ minWidth: 0 }} contentStyle={{ padding: "12px", display: "flex", flexDirection: "column", gap: 4, minHeight: 620 }}>
            <AgentSidebar agentList={agentList} agents={visibleAgents} activeAgent={selected} onSelect={setActiveAgent} />
          </LiquidGlass>

          {/* Detail panel */}
          <LiquidGlass style={{ minWidth: 0 }} contentStyle={{ padding: "20px 28px", minHeight: 620, display: "flex", flexDirection: "column" }}>
            {selectedState ? (
              <AgentDetail state={selectedState} planTask={selectedPlanTask} sessionId={sessionId} founderId={founderId} company={company || autoCompanyName} />
            ) : (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 200, color: "var(--fg-mute)", fontSize: 13 }}>Select an agent</div>
            )}
          </LiquidGlass>
        </div>
      )}

      {agentList.length > 0 && (
        <div className="blob-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 18, alignItems: "stretch" }}>
          <LiquidGlass contentStyle={{ padding: "26px 28px", display: "flex", flexDirection: "column", gap: 18, height: 420, minHeight: 420 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span className="site-label">Progress</span>
              <h3 style={{ fontSize: 18, margin: 0 }}>Session health</h3>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 18, flex: 1, minHeight: 0, overflowY: "auto", paddingRight: 4 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
                {[
                  ["Done", doneCount],
                  ["Running", runningCount],
                  ["Errors", failedCount],
                  ["Total", total],
                ].map(([label, value]) => (
                  <div key={label} style={{ padding: "11px 10px", borderRadius: 18, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(176,180,186,0.10)", display: "grid", gap: 4 }}>
                    <span style={{ fontSize: 17, color: "var(--fg)" }}>{value}</span>
                    <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</span>
                  </div>
                ))}
              </div>
              <div style={{ display: "grid", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                  <span style={{ fontSize: 12, color: "var(--fg-dim)" }}>Overall completion</span>
                  <span style={{ fontSize: 11, color: "var(--fg-mute)", fontFamily: "var(--font-jetbrains-mono)" }}>{total ? Math.round((doneCount / total) * 100) : 0}%</span>
                </div>
                <div style={{ height: 7, borderRadius: 999, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(176,180,186,0.10)", overflow: "hidden" }}>
                  <div style={{ width: `${total ? (doneCount / total) * 100 : 0}%`, height: "100%", borderRadius: 999, background: done ? "#3D9E5F" : "#2563EB", transition: "width 0.4s ease" }} />
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div style={{ padding: "12px 13px", borderRadius: 18, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)", display: "grid", gap: 3 }}>
                  <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Active lanes</span>
                  <span style={{ fontSize: 13, color: "var(--fg)", lineHeight: 1.45 }}>{activeAgents.length ? activeAgents.map(a => AGENT_LABELS[a] ?? a).join(" · ") : "No agents running"}</span>
                </div>
                <div style={{ padding: "12px 13px", borderRadius: 18, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)", display: "grid", gap: 3 }}>
                  <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Captured activity</span>
                  <span style={{ fontSize: 13, color: "var(--fg)", lineHeight: 1.45 }}>{totalVisitedUrls} sites visited · {totalCommits} commits</span>
                </div>
              </div>
            </div>
          </LiquidGlass>

          <LiquidGlass contentStyle={{ padding: "26px 28px", display: "flex", flexDirection: "column", gap: 18, height: 420, minHeight: 420 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span className="site-label">Plan</span>
              <h3 style={{ fontSize: 18, margin: 0 }}>Task graph</h3>
            </div>
            <div style={{ display: "grid", gap: 10, flex: 1, minHeight: 0, overflowY: "auto", paddingRight: 4 }}>
              {planTasks.length ? sortAgentNamesByOrder(planTasks.map(t => t.agent)).map((agentName, index) => {
                const task = planTasks.find(t => t.agent === agentName);
                const state = visibleAgents[agentName];
                if (!task) return null;
                return (
                  <div key={agentName} style={{ display: "grid", gridTemplateColumns: "22px 1fr", alignItems: "flex-start", gap: 10 }}>
                    <span style={{ width: 22, height: 22, borderRadius: 999, display: "grid", placeItems: "center", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(176,180,186,0.10)", color: "var(--fg-mute)", fontSize: 10, fontFamily: "var(--font-jetbrains-mono)" }}>{index + 1}</span>
                    <div style={{ display: "grid", gap: 3 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 12, color: "var(--fg)" }}>{AGENT_LABELS[agentName] ?? agentName}</span>
                        <span style={{ fontSize: 10, color: STATUS_COLOR[state?.status ?? "waiting"], textTransform: "uppercase", letterSpacing: "0.08em" }}>{state?.status ?? "waiting"}</span>
                      </div>
                      <span style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.45 }}>{task.instruction}</span>
                    </div>
                  </div>
                );
              }) : (
                <div style={{ padding: "12px 13px", borderRadius: 18, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)", color: "var(--fg-mute)", fontSize: 13, lineHeight: 1.6 }}>
                  Waiting for the planner to publish the task graph.
                </div>
              )}
            </div>
          </LiquidGlass>

          <LiquidGlass contentStyle={{ padding: "26px 28px", display: "flex", flexDirection: "column", gap: 18, height: 420, minHeight: 420 }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span className="site-label">Outputs</span>
                <h3 style={{ fontSize: 18, margin: 0 }}>Session artifacts</h3>
              </div>
              <span style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", whiteSpace: "nowrap", paddingTop: 3 }}>{completedAgents.length} ready</span>
            </div>
            <div style={{ padding: "13px 14px", borderRadius: 20, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(176,180,186,0.10)", display: "grid", gap: 5 }}>
              <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Selected lane</span>
              <span style={{ fontSize: 13, color: "var(--fg)", lineHeight: 1.45 }}>{AGENT_LABELS[selected] ?? selected}</span>
              <span style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.5 }}>{summarizeResult(selectedState)}</span>
            </div>
            <div style={{ display: "grid", gap: 10, flex: 1, minHeight: 0, overflowY: "auto", paddingRight: 4 }}>
              {completedArtifacts.length ? completedArtifacts.map((item) => (
                <button
                  key={item.agent}
                  type="button"
                  onClick={() => setActiveAgent(item.agent)}
                  style={{ display: "grid", gap: 4, padding: "11px 13px", borderRadius: 18, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)", textAlign: "left" }}
                >
                  <span style={{ fontSize: 12, color: "var(--fg)" }}>{item.label}</span>
                  <span style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.45 }}>{item.summary}</span>
                </button>
              )) : (
                <div style={{ padding: "12px 13px", borderRadius: 18, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)", color: "var(--fg-mute)", fontSize: 13, lineHeight: 1.6 }}>
                  Completed outputs will appear here as agents finish.
                </div>
              )}
            </div>
          </LiquidGlass>
        </div>
      )}

      {/* Bottom panels */}
      {connected && !error && !done && <SteerPanel sessionId={sessionId} isRunning={!done} />}
      {done && <CompanyChat priorSessionId={sessionId} founderId={founderId} company={company} />}


      {/* Agent Input Request Modal — shown when agent needs founder info */}
      {inputRequest && (
        <AgentInputModal
          sessionId={sessionId}
          request={inputRequest}
          onDone={() => setInputRequest(null)}
        />
      )}
      </div>
    </div>
  );
}
