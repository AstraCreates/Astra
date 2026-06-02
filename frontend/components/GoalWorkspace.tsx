"use client";

import { useCallback, useEffect, useState, useRef, useSyncExternalStore } from "react";
import type { CSSProperties } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { SignInButton, useUser } from "@clerk/nextjs";
import { apiFetch, streamGoal, continueSession, submitGoal, getStacks, getAgentCatalog, recommendStack, getStackReadiness, getConnectorCoverage, getConnectorSetup, getStackManifest, getSessionDigest, getSubteamReport, getSessionWorkboard, getSessionState, askSession, decideStackApproval, AGENT_LABELS, AGENT_ORDER, TOOL_DESCRIPTIONS, sortAgentNamesByOrder, getDeployment, publishDeployment } from "@/lib/api";
import type { DeploymentRecord } from "@/lib/api";
import type { AgentCatalogEntry } from "@/lib/api";
import type { AgentDepartmentManifest, AgentStackTemplate, ConnectorCoverage, ConnectorSetupPlan, SessionAnswer, SessionDigest, SessionStateSnapshot, SessionWorkboard, StackOperatingPlan, StackReadiness, StackRecommendation, SubteamReport } from "@/lib/api";
import { saveSession, getSessionSnapshot, subscribeSessions, deleteSession, clearAllSessions } from "@/lib/history";
import type { SessionRecord } from "@/lib/history";
import LiquidGlass from "@/components/LiquidGlass";
import CompanyChat from "@/components/CompanyChat";
import ThemeToggle from "@/components/ThemeToggle";
import WorkspaceTour from "@/components/WorkspaceTour";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface AgentTask { id: string; agent: string; instruction: string; }

interface StackArtifactState {
  key: string;
  title: string;
  owner_agent: string;
  description: string;
  required: boolean;
}

interface StackApprovalGateState {
  key: string;
  title: string;
  trigger: string;
  required_before: string;
  reason: string;
}

interface ApprovalQueueItemState extends StackApprovalGateState {
  status: "armed" | "triggered" | "approved" | "skipped";
  triggered_by?: string | null;
  note?: string | null;
}

interface StackConnectorRequirementState {
  key: string;
  label: string;
  category: string;
  purpose: string;
  required: boolean;
}

interface RunArtifactState extends StackArtifactState {
  status: "pending" | "ready";
  task_id?: string;
  preview?: string;
}

interface SafeRunActionState {
  id: string;
  tool: string;
  agent: string;
  risk_level: "low" | "medium" | "high";
  category: string;
  approval_gate: string;
  approval_required: boolean;
  mode: string;
  reason: string;
  status: "planned" | "waiting_approval" | "approved" | "executed" | "skipped" | "error";
  result_preview?: string;
}

interface OutcomeLedgerEvent {
  id: string;
  agent: string;
  task_id: string;
  metric: string;
  label: string;
  value: number;
  unit: string;
  source: string;
  preview?: string;
}

interface CompanyGenomeState {
  session_id: string;
  founder_id: string;
  company_name: string;
  goal: string;
  keywords: string[];
  stack: {
    id: string;
    name: string;
    target_user: string;
    primary_outcome: string;
    dashboard_sections: string[];
  };
  operating_model: {
    agent_lanes: Array<{ id: string; agent: string; title: string; artifacts: string[] }>;
    required_connectors: Array<{ key: string; label: string; category: string; purpose: string }>;
    optional_connectors: Array<{ key: string; label: string; category: string }>;
    approval_gates: Array<{ key: string; title: string; required_before: string; reason: string }>;
    expected_artifacts: Array<{ key: string; title: string; owner_agent: string; required: boolean }>;
  };
  memory: {
    prior_context_available: boolean;
    context_preview: string;
  };
}

interface LogEntry { ts: number; type: string; text: string; }

interface AgentState {
  task_id: string;
  agent: string;
  instruction: string;
  status: "waiting" | "running" | "done" | "error";
  currentAction: string | null;
  currentTool: string | null;
  lastToolAt: number | null;
  reasoning: string | null;
  model: string | null;
  tks: number | null;
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

const SUBTEAM_OPTIONS = ["engineering", "growth", "sales", "marketing", "product", "support", "ops", "legal"];

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

function WebPreview({ state, sessionId, founderId }: { state: AgentState; sessionId?: string; founderId?: string }) {
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
        {sessionId && founderId && (
          <DeploymentCard sessionId={sessionId} founderId={founderId} />
        )}
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

// ── DeploymentCard ─────────────────────────────────────────────────────────────

function DeploymentCard({ sessionId, founderId }: { sessionId: string; founderId: string }) {
  const [deployment, setDeployment] = useState<DeploymentRecord | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [domainInput, setDomainInput] = useState("");
  const [showForm, setShowForm] = useState(false);

  // Load or refresh deployment record
  const reload = useCallback(() => {
    if (!sessionId) return;
    getDeployment(sessionId).then(setDeployment).catch(() => {});
  }, [sessionId]);

  useEffect(() => {
    reload();
    // Poll every 10s while running (agent may deploy during a session)
    const interval = setInterval(reload, 10_000);
    return () => clearInterval(interval);
  }, [reload]);

  const handlePublish = async () => {
    if (!tokenInput.trim()) return;
    setPublishing(true);
    setPublishError(null);
    try {
      const result = await publishDeployment(sessionId, tokenInput.trim(), domainInput.trim() || undefined);
      if (result.ok) {
        setShowForm(false);
        setDeployment(prev => prev ? { ...prev, status: "published", prod_url: result.prod_url, published_at: new Date().toISOString() } : prev);
        reload();
      } else {
        setPublishError(result.error ?? "Publish failed");
      }
    } catch (err) {
      setPublishError(err instanceof Error ? err.message : "Publish failed");
    } finally {
      setPublishing(false);
    }
  };

  if (!deployment || deployment.status === "none") return null;

  const isPublished = deployment.status === "published";

  return (
    <div style={{
      borderRadius: 14,
      border: "1px solid rgba(37,99,235,0.2)",
      background: "rgba(37,99,235,0.04)",
      padding: "14px 16px",
      display: "flex",
      flexDirection: "column",
      gap: 10,
      marginTop: 8,
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <span style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "#2563EB", fontWeight: 600 }}>
          Deployment
        </span>
        {isPublished && (
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase",
            color: "#fff", background: "#3D9E5F", borderRadius: 6, padding: "2px 8px",
          }}>
            Live
          </span>
        )}
        {!isPublished && (
          <span style={{
            fontSize: 10, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase",
            color: "#2563EB", background: "rgba(37,99,235,0.1)", borderRadius: 6, padding: "2px 8px",
          }}>
            Staged
          </span>
        )}
      </div>

      {/* Staging URL */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.07em" }}>Preview (Staging)</span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{
            fontSize: 11, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg-dim)",
            flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {deployment.staging_url.replace(/^https?:\/\//, "")}
          </span>
          <a
            href={deployment.staging_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 10, color: "#2563EB", textDecoration: "none", flexShrink: 0 }}
            title="Open preview"
          >
            ↗
          </a>
        </div>
      </div>

      {/* Prod URL if published */}
      {isPublished && deployment.prod_url && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 10, color: "#3D9E5F", textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600 }}>Production URL</span>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{
              fontSize: 11, fontFamily: "var(--font-jetbrains-mono)", color: "var(--fg)",
              flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              fontWeight: 600,
            }}>
              {deployment.prod_url.replace(/^https?:\/\//, "")}
            </span>
            <a
              href={deployment.prod_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontSize: 10, color: "#3D9E5F", textDecoration: "none", flexShrink: 0 }}
              title="Open production site"
            >
              ↗
            </a>
          </div>
        </div>
      )}

      {/* Publish to Production button / form */}
      {!isPublished && !showForm && (
        <button
          onClick={() => setShowForm(true)}
          style={{
            padding: "8px 16px", borderRadius: 9, border: "none", cursor: "pointer",
            background: "linear-gradient(135deg,#2563EB,#1d4ed8)",
            color: "#fff", fontSize: 12, fontWeight: 600,
            alignSelf: "flex-start",
          }}
        >
          Publish to Production
        </button>
      )}

      {!isPublished && showForm && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <input
            type="password"
            placeholder="Vercel API token (required)"
            value={tokenInput}
            onChange={e => setTokenInput(e.target.value)}
            style={{
              fontSize: 12, padding: "7px 10px", borderRadius: 8,
              border: "1px solid rgba(37,99,235,0.3)", background: "var(--glass)",
              color: "var(--fg)", outline: "none", width: "100%", boxSizing: "border-box",
            }}
          />
          <input
            type="text"
            placeholder="Custom domain (optional, e.g. mysite.com)"
            value={domainInput}
            onChange={e => setDomainInput(e.target.value)}
            style={{
              fontSize: 12, padding: "7px 10px", borderRadius: 8,
              border: "1px solid rgba(0,0,0,0.15)", background: "var(--glass)",
              color: "var(--fg)", outline: "none", width: "100%", boxSizing: "border-box",
            }}
          />
          {publishError && (
            <div style={{ fontSize: 11, color: "#C0392B", padding: "6px 10px", borderRadius: 8, background: "rgba(192,57,43,0.08)", border: "1px solid rgba(192,57,43,0.2)" }}>
              {publishError}
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={handlePublish}
              disabled={publishing || !tokenInput.trim()}
              style={{
                flex: 1, padding: "8px 16px", borderRadius: 9, border: "none",
                cursor: publishing || !tokenInput.trim() ? "not-allowed" : "pointer",
                background: publishing || !tokenInput.trim() ? "rgba(37,99,235,0.3)" : "linear-gradient(135deg,#2563EB,#1d4ed8)",
                color: "#fff", fontSize: 12, fontWeight: 600,
              }}
            >
              {publishing ? "Publishing…" : "Confirm Publish"}
            </button>
            <button
              onClick={() => { setShowForm(false); setPublishError(null); }}
              style={{
                padding: "8px 14px", borderRadius: 9, border: "1px solid rgba(0,0,0,0.15)",
                cursor: "pointer", background: "transparent", color: "var(--fg-mute)", fontSize: 12,
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {isPublished && deployment.published_at && (
        <div style={{ fontSize: 10, color: "var(--fg-mute)" }}>
          Published {new Date(deployment.published_at).toLocaleString()}
        </div>
      )}
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

function AgentPreview({ state, founderId, company, sessionId }: { state: AgentState; founderId?: string; company?: string; sessionId?: string }) {
  switch (state.agent) {
    case "research":
    case "research_competitors":
    case "research_execution":
      return <ResearchPreview state={state} />;
    case "web": return <WebPreview state={state} sessionId={sessionId} founderId={founderId} />;
    case "technical": return <TechnicalPreview state={state} />;
    case "design": return <DesignPreview state={state} />;
    case "marketing": return <MarketingPreview state={state} />;
    case "legal": return <LegalPreview state={state} founderId={founderId} company={company} />;
    case "sales": return <SalesPreview state={state} />;
    case "ops": return <OpsPreview state={state} />;
    default: return <BuildingIndicator label="Working…" />;
  }
}

// ── Agent chat ─────────────────────────────────────────────────────────────

interface AgentChatMsg { role: "user" | "agent"; text: string; }

function AgentChat({ agentKey, founderId, sessionId, company, goal }: { agentKey: string; founderId: string; sessionId?: string; company?: string; goal?: string }) {
  const storageKey = `astra_chat_${sessionId ?? "nosession"}_${agentKey}`;

  const loadMsgs = (key: string): AgentChatMsg[] => {
    try { return JSON.parse(localStorage.getItem(key) ?? "[]"); } catch { return []; }
  };

  const [msgs, setMsgs] = useState<AgentChatMsg[]>(() => loadMsgs(storageKey));
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const label = AGENT_LABELS[agentKey] ?? agentKey;

  // Reload history when switching agents
  useEffect(() => {
    setMsgs(loadMsgs(storageKey));
    setInput("");
  }, [storageKey]);

  // Persist on every change
  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify(msgs)); } catch {}
  }, [msgs, storageKey]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

  const send = async () => {
    const q = input.trim();
    if (!q || loading) return;
    setInput("");
    setMsgs(m => [...m, { role: "user", text: q }]);
    setLoading(true);
    try {
      const res = await apiFetch(`${BASE}/chat/${agentKey}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_agent: agentKey, question: q, founder_id: founderId, session_id: sessionId, company_name: company || undefined, goal: goal || undefined }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      const data = await res.json();
      const reply = typeof data.response === "string" ? data.response : JSON.stringify(data.response);
      setMsgs(m => [...m, { role: "agent", text: reply }]);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setMsgs(m => [...m, { role: "agent", text: `⚠ ${msg}` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      borderTop: "1px solid var(--line-2)",
      paddingTop: 14,
      display: "flex",
      flexDirection: "column",
      gap: 10,
      marginTop: 4,
    }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: "var(--fg-mute)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
        Ask {label}
      </span>

      {msgs.length > 0 && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 8,
          maxHeight: 260, overflowY: "auto",
          padding: "10px 12px", borderRadius: 14,
          background: "rgba(180,205,228,0.06)",
          border: "1px solid var(--line-2)",
        }}>
          {msgs.map((m, i) => (
            <div key={i} style={{
              display: "flex",
              justifyContent: m.role === "user" ? "flex-end" : "flex-start",
            }}>
              <div style={{
                maxWidth: "85%",
                padding: "8px 12px",
                borderRadius: m.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
                background: m.role === "user"
                  ? "linear-gradient(135deg,#3b82f6,#6366f1)"
                  : "rgba(180,205,228,0.12)",
                border: m.role === "agent" ? "1px solid var(--line-2)" : "none",
                fontSize: 12,
                lineHeight: 1.6,
                color: m.role === "user" ? "#fff" : "var(--fg-dim)",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}>
                {m.text}
              </div>
            </div>
          ))}
          {loading && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 2px" }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#3b82f6", animation: "blink 0.8s infinite" }} />
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#3b82f6", animation: "blink 0.8s 0.15s infinite" }} />
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#3b82f6", animation: "blink 0.8s 0.3s infinite" }} />
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder={`Ask ${label} something…`}
          disabled={loading}
          style={{
            flex: 1, padding: "9px 14px", borderRadius: 10,
            background: "rgba(180,205,228,0.07)",
            border: "1px solid var(--line-2)",
            color: "var(--fg)", fontSize: 12, outline: "none",
          }}
        />
        <button onClick={send} disabled={loading || !input.trim()}
          style={{
            padding: "0 16px", borderRadius: 10, border: "none",
            background: loading || !input.trim() ? "rgba(59,130,246,0.3)" : "linear-gradient(135deg,#3b82f6,#6366f1)",
            color: "#fff", fontSize: 12, fontWeight: 600, cursor: loading ? "wait" : "pointer",
            transition: "background 0.2s",
          }}>
          {loading ? "…" : "Send"}
        </button>
      </div>
      <style>{`@keyframes blink{0%,100%{opacity:0.2}50%{opacity:1}}`}</style>
    </div>
  );
}

// ── Agent detail panel ──────────────────────────────────────────────────────

type DetailTab = "preview" | "plan" | "log" | "obsidian";

function AgentDetail({
  state,
  planTask,
  sessionId,
  founderId,
  company,
  goal,
}: {
  state: AgentState;
  planTask: AgentTask | undefined;
  sessionId: string;
  founderId: string;
  company?: string;
  goal?: string;
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
    apiFetch(`${BASE}/vault/${encodeURIComponent(founderId)}/note?session_id=${encodeURIComponent(sessionId)}&agent=${encodeURIComponent(state.agent)}`, {
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
        {tab === "preview" && <AgentPreview state={state} founderId={founderId} company={company} sessionId={sessionId} />}

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

function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function AgentSidebar({ agentList, agents, activeAgent, onSelect }: {
  agentList: string[];
  agents: Record<string, AgentState>;
  activeAgent: string;
  onSelect: (a: string) => void;
}) {
  const now = useNow(1000);
  return (
    <div data-tour="agent-tabs" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {agentList.map(name => {
        const state = agents[name];
        const status = state?.status ?? "waiting";
        const isActive = name === activeAgent;
        const isRunning = status === "running";
        const tool = state?.currentTool;
        const lastToolAt = state?.lastToolAt;
        const secsAgo = lastToolAt ? Math.floor((now - lastToolAt) / 1000) : null;
        const agoLabel = secsAgo !== null
          ? secsAgo < 60 ? `${secsAgo}s ago` : `${Math.floor(secsAgo / 60)}m ago`
          : null;
        const toolLabel = tool ? tool.replace(/_/g, " ") : null;
        const modelShort = state?.model
          ? state.model.split("/").pop()?.replace(/:free$/, "") ?? null
          : null;
        const tks = state?.tks ?? null;

        return (
          <button key={name} onClick={() => onSelect(name)} style={{
            display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 3,
            padding: "5px 10px 5px 8px",
            borderRadius: 999,
            border: `1px solid ${isActive ? "#2563EB" : isRunning ? "rgba(37,99,235,0.35)" : "var(--line)"}`,
            background: isActive ? "#EFF6FF" : isRunning ? "rgba(37,99,235,0.05)" : "rgba(255,255,255,0.03)",
            cursor: "pointer", transition: "background 0.15s, border-color 0.15s",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 14 }}>{AGENT_ICONS[name] ?? "🤖"}</span>
              <span style={{ fontSize: 11, fontWeight: 600, color: isActive ? "#2563EB" : isRunning ? "#374151" : "var(--fg-mute)", whiteSpace: "nowrap" }}>
                {AGENT_LABELS[name] ?? name}
              </span>
              <span style={{
                width: 5, height: 5, borderRadius: "50%", flexShrink: 0,
                background: status === "done" ? "#22C55E" : status === "running" ? "#2563EB" : status === "error" ? "#EF4444" : "rgba(255,255,255,0.15)",
              }} className={status === "running" ? "animate-pulse" : ""} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 4, paddingLeft: 20 }}>
              {modelShort && (
                <span style={{ fontSize: 9, color: "#2563EB", whiteSpace: "nowrap", fontFamily: "var(--font-jetbrains-mono)", opacity: 0.8 }}>
                  {modelShort}
                </span>
              )}
              {isRunning && tks !== null && (
                <span style={{ fontSize: 9, color: "#22C55E", whiteSpace: "nowrap", fontFamily: "var(--font-jetbrains-mono)" }}>
                  {tks}t/s
                </span>
              )}
              {isRunning && toolLabel && (
                <span style={{ fontSize: 9, color: "#6B7280", whiteSpace: "nowrap", maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis" }}>
                  · {toolLabel}{agoLabel ? ` ${agoLabel}` : ""}
                </span>
              )}
            </div>
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
      const res = await apiFetch(`${BASE}/input/${sessionId}/${request.request_id}`, {
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

interface UChatMsg { id: string; role: "user" | "agent" | "system"; agent?: string; text: string; }

function UnifiedChat({ sessionId, founderId, company, goal, done, connected, agents }: {
  sessionId: string; founderId: string; company?: string; goal?: string;
  done: boolean; connected: boolean; agents: string[];
}) {
  const storageKey = `astra_uchat_${sessionId}`;
  const [msgs, setMsgs] = useState<UChatMsg[]>(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) ?? "[]"); } catch { return []; }
  });
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionQ, setMentionQ] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { try { localStorage.setItem(storageKey, JSON.stringify(msgs)); } catch {} }, [msgs, storageKey]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const handleChange = (val: string) => {
    setInput(val);
    const lastAt = val.lastIndexOf("@");
    if (lastAt >= 0 && !val.slice(lastAt).includes(" ")) {
      setMentionQ(val.slice(lastAt + 1).toLowerCase());
      setMentionOpen(true);
    } else {
      setMentionOpen(false);
    }
  };

  const insertMention = (a: string) => {
    const lastAt = input.lastIndexOf("@");
    setInput(input.slice(0, lastAt) + `@${a} `);
    setMentionOpen(false);
  };

  const send = async () => {
    const q = input.trim();
    if (!q || loading) return;
    setInput(""); setMentionOpen(false);
    const userMsg: UChatMsg = { id: Date.now().toString(), role: "user", text: q };
    setMsgs(m => [...m, userMsg]);
    setLoading(true);
    try {
      const mentionMatch = q.match(/^@([\w_-]+)\s+([\s\S]+)$/);
      if (mentionMatch) {
        const [, agent, question] = mentionMatch;
        const res = await apiFetch(`${BASE}/chat/${agent}`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target_agent: agent, question, founder_id: founderId, session_id: sessionId, company_name: company, goal }),
        });
        const data = await res.json();
        setMsgs(m => [...m, { id: Date.now().toString(), role: "agent", agent, text: data.response ?? JSON.stringify(data) }]);
      } else if (!done && connected) {
        await apiFetch(`${BASE}/steer/${sessionId}`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: q }),
        });
        setMsgs(m => [...m, { id: Date.now().toString(), role: "system", text: "↑ Sent to all running agents" }]);
      } else {
        const res = await apiFetch(`${BASE}/sessions/${sessionId}/ask`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: q, founder_id: founderId }),
        });
        const data = await res.json().catch(() => ({}));
        setMsgs(m => [...m, { id: Date.now().toString(), role: "agent", agent: "astra", text: data.answer ?? data.response ?? "No response" }]);
      }
    } catch (e) {
      setMsgs(m => [...m, { id: Date.now().toString(), role: "agent", text: `⚠ ${e instanceof Error ? e.message : "Error"}` }]);
    } finally { setLoading(false); }
  };

  const filteredAgents = agents.filter(a => a.toLowerCase().includes(mentionQ));
  const placeholder = !connected && !done ? "Waiting for session…"
    : done ? "Ask about results… or @research what was the TAM?"
    : "Steer all agents… or @legal what entity should I form?";

  return (
    <div data-tour="unified-chat" style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 16, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "#111827" }}>
          {done ? "Ask Astra" : "Chat"}
        </span>
        <span style={{ fontSize: 11, color: "#9CA3AF" }}>
          @agent to route · plain message {done ? "asks about results" : "steers all agents"}
        </span>
      </div>

      {msgs.length > 0 && (
        <div style={{ maxHeight: 280, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8, padding: "4px 0" }}>
          {msgs.map(m => (
            <div key={m.id} style={{ display: "flex", gap: 8, justifyContent: m.role === "user" ? "flex-end" : "flex-start", alignItems: "flex-end" }}>
              {m.role !== "user" && (
                <span style={{ fontSize: 10, color: "#6B7280", fontWeight: 700, whiteSpace: "nowrap", marginBottom: 2 }}>
                  {m.agent ? `@${m.agent}` : "·"}
                </span>
              )}
              <div style={{
                maxWidth: "75%", padding: "8px 12px", borderRadius: 12, fontSize: 13, lineHeight: 1.6, wordBreak: "break-word", whiteSpace: "pre-wrap",
                background: m.role === "user" ? "#2563EB" : m.role === "system" ? "#EFF6FF" : "#F8F9FA",
                color: m.role === "user" ? "#fff" : m.role === "system" ? "#1D4ED8" : "#111827",
                border: m.role === "user" ? "none" : "1px solid #E5E7EB",
                fontStyle: m.role === "system" ? "italic" : "normal",
              }}>{m.text}</div>
            </div>
          ))}
          {loading && <div style={{ fontSize: 12, color: "#9CA3AF", display: "flex", alignItems: "center", gap: 6 }}><span className="animate-pulse" style={{ color: "#2563EB" }}>●</span> Thinking…</div>}
          <div ref={bottomRef} />
        </div>
      )}

      <div style={{ position: "relative" }}>
        {mentionOpen && filteredAgents.length > 0 && (
          <div style={{
            position: "absolute", bottom: "calc(100% + 6px)", left: 0, right: 0,
            background: "#fff", border: "1px solid #E5E7EB", boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
            borderRadius: 12, padding: 8, display: "flex", flexWrap: "wrap", gap: 4, zIndex: 20,
          }}>
            {filteredAgents.slice(0, 12).map(a => (
              <button key={a} type="button" onClick={() => insertMention(a)}
                style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, border: "1px solid #E5E7EB", background: "#F8F9FA", cursor: "pointer", color: "#374151" }}>
                @{a}
              </button>
            ))}
          </div>
        )}
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={input} onChange={e => handleChange(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder={placeholder}
            style={{ flex: 1, padding: "10px 16px", fontSize: 13, borderRadius: 999, border: "1px solid #E5E7EB", background: "#F8F9FA", color: "#111827", outline: "none" }}
          />
          <button onClick={send} disabled={loading || !input.trim()}
            style={{ padding: "0 20px", borderRadius: 999, fontSize: 13, background: loading || !input.trim() ? "#E5E7EB" : "#2563EB", color: loading || !input.trim() ? "#9CA3AF" : "#fff", border: "none", cursor: loading || !input.trim() ? "default" : "pointer", fontWeight: 600 }}>
            {loading ? "…" : "↑"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AskPanel({ sessionId, founderId }: { sessionId: string; founderId: string }) {
  const [msg, setMsg] = useState(""); const [reply, setReply] = useState(""); const [loading, setLoading] = useState(false);
  const ask = async () => {
    if (!msg.trim()) return;
    setLoading(true); setReply("");
    const r = await apiFetch(`${BASE}/ask`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, founder_id: founderId, question: msg }) });
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
  const [techStack, setTechStack] = useState({ frontend: "Next.js", backend: "FastAPI", database: "Supabase (Postgres)", auth: "Clerk" });
  const [stackTemplates, setStackTemplates] = useState<AgentStackTemplate[]>([]);
  const [selectedStackId, setSelectedStackId] = useState("idea_to_revenue");
  const [stackRecommendation, setStackRecommendation] = useState<StackRecommendation | null>(null);
  const [stackReadiness, setStackReadiness] = useState<StackReadiness | null>(null);
  const [manualStackOverride, setManualStackOverride] = useState(false);
  const REQUIRED_AGENTS = new Set(["research"]);
  const [customAgents, setCustomAgents] = useState<string[]>(["research", "web", "technical", "marketing"]);
  const [customPickerOpen, setCustomPickerOpen] = useState(true);
  const [agentCatalog, setAgentCatalog] = useState<AgentCatalogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    getStacks()
      .then(stacks => {
        if (cancelled) return;
        setStackTemplates(stacks);
        if (stacks.length && selectedStackId !== "custom" && !stacks.some(stack => stack.stack_id === selectedStackId)) {
          setSelectedStackId(stacks[0].stack_id);
        }
      })
      .catch(() => {
        if (!cancelled) setStackTemplates([]);
      });
    getAgentCatalog().then(c => { if (!cancelled) setAgentCatalog(c); }).catch(() => {});
    return () => { cancelled = true; };
  }, [open, selectedStackId]);

  useEffect(() => {
    if (!open || instruction.trim().length < 16) {
      setStackRecommendation(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      recommendStack(instruction)
        .then(recommendation => {
          if (controller.signal.aborted) return;
          setStackRecommendation(recommendation);
          if (!manualStackOverride) setSelectedStackId(recommendation.stack.stack_id);
        })
        .catch(() => {
          if (!controller.signal.aborted) setStackRecommendation(null);
        });
    }, 350);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [open, instruction, manualStackOverride]);

  useEffect(() => {
    if (!open || !selectedStackId) return;
    let cancelled = false;
    const founderId = user?.id ?? "anon";
    getStackReadiness(founderId, selectedStackId)
      .then(readiness => { if (!cancelled) setStackReadiness(readiness); })
      .catch(() => { if (!cancelled) setStackReadiness(null); });
    return () => { cancelled = true; };
  }, [open, selectedStackId, user?.id]);

  const selectedStack = stackTemplates.find(stack => stack.stack_id === selectedStackId);

  if (!open) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!instruction.trim()) return;
    setLoading(true);
    setError(null);
    const parts = [
      companyName.trim() && `Company name: ${companyName.trim()}.`,
      domain.trim() && `Domain: ${domain.trim()}.`,
      selectedStack && `Agent stack: ${selectedStack.name}. Outcome: ${selectedStack.primary_outcome}.`,
      showStack && `Tech stack: Frontend=${techStack.frontend}, Backend=${techStack.backend}, Database=${techStack.database}, Auth=${techStack.auth}.`,
    ].filter(Boolean);
    const full = parts.length ? `${parts.join(" ")}\n\n${instruction}` : instruction;
    const founderId = user?.id ?? "anon";
    try {
      const constraints: Record<string, unknown> = selectedStackId === "custom" ? { agents: customAgents } : {};
      const result = await submitGoal(founderId, full, constraints, selectedStackId);
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
      <LiquidGlass style={{ width: "min(1120px, 100%)", maxHeight: "calc(100vh - 48px)" }} contentStyle={{ padding: "28px 30px", display: "flex", flexDirection: "column", gap: 18, maxHeight: "calc(100vh - 48px)", overflowY: "auto" }}>
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
          <div style={{ border: "1px solid var(--line)", borderRadius: 28, padding: "14px 16px", display: "grid", gap: 12, background: "rgba(255,255,255,0.03)" }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 14 }}>
              <div style={{ display: "grid", gap: 5 }}>
                <span className="site-label">Agent stack</span>
                <strong style={{ color: "var(--fg)", fontSize: 15 }}>{selectedStack?.name ?? "Idea to Revenue Stack"}</strong>
                <span style={{ color: "var(--fg-dim)", fontSize: 12, lineHeight: 1.55 }}>
                  {selectedStack?.description ?? "Astra will build the company foundation: research, positioning, brand, landing page, roadmap, GTM, sales workflow, legal starter kit, and 30-day operating plan."}
                </span>
              </div>
              <span style={{ border: "1px solid var(--line)", borderRadius: 999, padding: "7px 11px", color: "var(--fg-dim)", fontSize: 11, whiteSpace: "nowrap" }}>
                {selectedStack?.artifacts.length ?? 18} outputs
              </span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 8 }}>
              {(stackTemplates.length ? stackTemplates : [{
                stack_id: "idea_to_revenue",
                name: "Idea to Revenue Stack",
                target_user: "Founders starting from a rough startup idea.",
                primary_outcome: "Turn an idea into a launch-ready company foundation.",
                description: "Company foundation, launch surface, GTM, sales, legal, and 30-day plan.",
                input_prompts: [],
                tasks: [],
                artifacts: [],
                approval_gates: [],
                connector_requirements: [],
                dashboard_sections: [],
                completion_rules: [],
              }]).map(stackTemplate => {
                const active = stackTemplate.stack_id === selectedStackId;
                return (
                  <button
                    key={stackTemplate.stack_id}
                    type="button"
                    onClick={() => {
                      setManualStackOverride(true);
                      setSelectedStackId(stackTemplate.stack_id);
                    }}
                    disabled={loading}
                    style={{
                      display: "grid",
                      gap: 5,
                      textAlign: "left",
                      borderRadius: 20,
                      border: `1px solid ${active ? "rgba(61,158,95,0.38)" : "var(--line)"}`,
                      background: active ? "rgba(61,158,95,0.10)" : "rgba(255,255,255,0.025)",
                      color: "var(--fg)",
                      padding: "10px 11px",
                      cursor: "pointer",
                    }}
                  >
                      <span style={{ fontSize: 12, fontWeight: 650 }}>{stackTemplate.name.replace(" Stack", "")}</span>
                      <span style={{ fontSize: 10, color: active ? "#3D9E5F" : "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {stackRecommendation?.stack.stack_id === stackTemplate.stack_id ? "Recommended" : `${stackTemplate.tasks.length || "Template"} lanes`}
                    </span>
                  </button>
                );
              })}
              {/* Custom stack option */}
              {(() => {
                const active = selectedStackId === "custom";
                return (
                  <button
                    type="button"
                    onClick={() => { setManualStackOverride(true); setSelectedStackId("custom"); setCustomPickerOpen(true); }}
                    disabled={loading}
                    style={{
                      display: "grid", gap: 5, textAlign: "left", borderRadius: 20,
                      border: `1px solid ${active ? "rgba(99,102,241,0.45)" : "var(--line)"}`,
                      background: active ? "rgba(99,102,241,0.10)" : "rgba(255,255,255,0.025)",
                      color: "var(--fg)", padding: "10px 11px", cursor: "pointer",
                    }}
                  >
                    <span style={{ fontSize: 12, fontWeight: 650 }}>✨ Custom</span>
                    <span style={{ fontSize: 10, color: active ? "#818cf8" : "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {active ? `${customAgents.length} agents` : "Pick your own"}
                    </span>
                  </button>
                );
              })()}
            </div>
            {/* Custom agent picker */}
            {selectedStackId === "custom" && agentCatalog.length > 0 && (() => {
              const GROUP_ORDER = ["research", "legal", "marketing", "sales", "technical", "finance", "ops", "web", "design"];
              const GROUP_LABELS: Record<string, string> = {
                research: "Research", legal: "Legal", marketing: "Marketing",
                sales: "Sales", technical: "Technical", finance: "Finance",
                ops: "Ops", web: "Web", design: "Design",
              };
              const header = (
                <div
                  onClick={() => setCustomPickerOpen(o => !o)}
                  style={{ display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer", padding: "6px 0" }}
                >
                  <span style={{ fontSize: 11, fontWeight: 600, color: "var(--fg-dim)" }}>
                    {customAgents.length} agent{customAgents.length === 1 ? "" : "s"} selected
                  </span>
                  <span style={{ fontSize: 11, color: "#818cf8" }}>{customPickerOpen ? "▲ collapse" : "▼ edit agents"}</span>
                </div>
              );
              if (!customPickerOpen) return <div style={{ padding: "4px 0" }}>{header}</div>;
              const GROUP_EMOJI: Record<string, string> = {
                research: "🔍", legal: "⚖️", marketing: "📣", sales: "💰",
                technical: "⚙️", finance: "📊", ops: "🧭", web: "🌐", design: "🎨",
              };
              const grouped: Record<string, AgentCatalogEntry[]> = {};
              agentCatalog.forEach(agent => {
                const group = agent.id.includes("_") ? agent.id.split("_")[0] : agent.id;
                if (!grouped[group]) grouped[group] = [];
                grouped[group].push(agent);
              });
              const picker = (
                <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "12px 0 4px", maxHeight: 360, overflowY: "auto" }}>
                  {GROUP_ORDER.filter(g => grouped[g]).map(group => (
                    <div key={group}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 5, display: "flex", alignItems: "center", gap: 5 }}>
                        <span>{GROUP_EMOJI[group]}</span>{GROUP_LABELS[group]}
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 5 }}>
                        {grouped[group].map(agent => {
                          const on = customAgents.includes(agent.id);
                          const required = REQUIRED_AGENTS.has(agent.id);
                          return (
                            <button
                              key={agent.id}
                              type="button"
                              onClick={() => { if (!required) setCustomAgents(prev => on ? prev.filter(a => a !== agent.id) : [...prev, agent.id]); }}
                              disabled={loading || required}
                              style={{
                                display: "flex", alignItems: "flex-start", flexDirection: "column", gap: 2,
                                padding: "7px 10px", borderRadius: 12, textAlign: "left",
                                border: `1px solid ${on ? "rgba(99,102,241,0.45)" : "var(--line)"}`,
                                background: on ? "rgba(99,102,241,0.10)" : "rgba(255,255,255,0.02)",
                                cursor: required ? "default" : "pointer",
                                opacity: required ? 0.75 : 1,
                              }}
                            >
                              <span style={{ fontSize: 11, fontWeight: 600, color: on ? "#a5b4fc" : "var(--fg)" }}>
                                {agent.name}{required ? <span style={{ marginLeft: 5, fontSize: 9, color: "#818cf8", textTransform: "uppercase", letterSpacing: "0.06em" }}>required</span> : on && <span style={{ marginLeft: 5, color: "#818cf8" }}>✓</span>}
                              </span>
                              <span style={{ fontSize: 10, color: "var(--fg-mute)", lineHeight: 1.35 }}>{agent.description.slice(0, 60)}…</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: 6 }}>
                    <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>
                      {customAgents.length === 0 ? "Select at least 1 agent" : `${customAgents.length} agent${customAgents.length === 1 ? "" : "s"} selected`}
                    </span>
                    <button
                      type="button"
                      onClick={() => setCustomPickerOpen(false)}
                      disabled={customAgents.length === 0}
                      style={{ padding: "5px 14px", borderRadius: 999, background: "#6366f1", color: "#fff", border: "none", fontSize: 12, fontWeight: 600, cursor: "pointer", opacity: customAgents.length === 0 ? 0.4 : 1 }}
                    >
                      Done →
                    </button>
                  </div>
                </div>
              );
              return <>{header}{picker}</>;
            })()}
            {stackRecommendation && (
              <div style={{ display: "grid", gap: 6, borderRadius: 20, border: "1px solid rgba(61,158,95,0.18)", background: "rgba(61,158,95,0.06)", padding: "10px 12px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                  <span className="site-label">Stack compiler</span>
                  <span style={{ fontSize: 11, color: "#3D9E5F", fontFamily: "var(--font-jetbrains-mono)" }}>{Math.round(stackRecommendation.confidence * 100)}%</span>
                </div>
                <span style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.45 }}>{stackRecommendation.reason}</span>
                {stackRecommendation.matched_signals.length > 0 && (
                  <span style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.45 }}>
                    Signals: {stackRecommendation.matched_signals.join(" · ")}
                  </span>
                )}
              </div>
            )}
            {stackReadiness && (
              <div style={{ display: "grid", gap: 7, borderRadius: 20, border: `1px solid ${stackReadiness.ready ? "rgba(61,158,95,0.18)" : "rgba(245,158,11,0.22)"}`, background: stackReadiness.ready ? "rgba(61,158,95,0.05)" : "rgba(245,158,11,0.06)", padding: "10px 12px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                  <span className="site-label">Stack readiness</span>
                  <span style={{ fontSize: 11, color: stackReadiness.ready ? "#3D9E5F" : "#D97706", fontFamily: "var(--font-jetbrains-mono)" }}>
                    {stackReadiness.readiness_score}%
                  </span>
                </div>
                <span style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.45 }}>
                  {stackReadiness.connected_required}/{stackReadiness.required_total} required connectors ready
                  {stackReadiness.missing_required > 0 ? ` · ${stackReadiness.missing_required} missing` : " · ready to operate"}
                </span>
                {stackReadiness.next_actions.slice(0, 2).map(action => (
                  <span key={action} style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.45 }}>- {action}</span>
                ))}
              </div>
            )}
          </div>

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
                    <select value={techStack[key as keyof typeof techStack]} onChange={e => setTechStack(p => ({ ...p, [key]: e.target.value }))} disabled={loading} className="site-input" style={{ padding: "8px 10px", fontSize: 12, background: "linear-gradient(135deg, rgba(255,255,255,0.08), rgba(180,205,228,0.04)), var(--glass-hi)" }}>
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

// ── Launch Checklist ─────────────────────────────────────────────────────────

function LaunchChecklist({ sessionId, done, agents, agentList, selectedStack }: {
  sessionId: string; done: boolean;
  agents: Record<string, AgentState>;
  agentList: string[];
  selectedStack: AgentStackTemplate | null;
}) {
  const [open, setOpen] = useState(true);
  const agentDone = (name: string) => agents[name]?.status === "done";
  const has = (name: string) => agentList.includes(name);

  const items = [
    { id: "goal",      label: "Goal launched",          done: !!sessionId },
    { id: "stack",     label: "Stack selected",         done: !!selectedStack },
    ...(has("research")  ? [{ id: "research",  label: "Research complete",       done: agentDone("research") }]  : []),
    ...(has("web")       ? [{ id: "web",       label: "Website built",           done: agentDone("web") }]       : []),
    ...(has("technical") ? [{ id: "technical", label: "Technical scaffold done", done: agentDone("technical") }] : []),
    ...(has("legal")     ? [{ id: "legal",     label: "Legal docs drafted",      done: agentDone("legal") }]     : []),
    ...(has("marketing") ? [{ id: "marketing", label: "Marketing assets ready",  done: agentDone("marketing") }] : []),
    ...(has("sales")     ? [{ id: "sales",     label: "Sales pipeline built",    done: agentDone("sales") }]     : []),
    { id: "complete",  label: "Run complete",           done },
  ];

  const doneCount = items.filter(i => i.done).length;
  const pct = items.length > 0 ? Math.round((doneCount / items.length) * 100) : 0;
  const allDone = pct === 100;

  useEffect(() => { if (done) setOpen(false); }, [done]);

  return (
    <div data-tour="launch-checklist" style={{
      borderRadius: 14, overflow: "hidden", transition: "border-color 0.3s, background 0.3s",
      border: `1px solid ${allDone ? "rgba(61,158,95,0.3)" : "var(--line)"}`,
      background: allDone ? "rgba(61,158,95,0.04)" : "rgba(255,255,255,0.02)",
    }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "11px 16px", background: "none", border: "none", cursor: "pointer", gap: 12, textAlign: "left",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>Launch checklist</span>
          <span style={{
            fontSize: 11, padding: "1px 8px", borderRadius: 999, fontWeight: 600,
            background: allDone ? "rgba(61,158,95,0.12)" : "rgba(37,99,235,0.10)",
            color: allDone ? "#3D9E5F" : "#2563EB",
          }}>{doneCount}/{items.length}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 64, height: 3, borderRadius: 999, background: "var(--line-2)", overflow: "hidden" }}>
            <div style={{ height: "100%", borderRadius: 999, width: `${pct}%`, background: allDone ? "#3D9E5F" : "#2563EB", transition: "width 0.5s" }} />
          </div>
          <span style={{ fontSize: 10, color: "var(--fg-mute)" }}>{open ? "▲" : "▼"}</span>
        </div>
      </button>
      {open && (
        <div style={{ borderTop: "1px solid var(--line-2)", padding: "10px 16px 14px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 16px" }}>
          {items.map(item => (
            <div key={item.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{
                width: 16, height: 16, borderRadius: "50%", flexShrink: 0,
                display: "flex", alignItems: "center", justifyContent: "center",
                background: item.done ? "rgba(61,158,95,0.15)" : "transparent",
                border: `1.5px solid ${item.done ? "#3D9E5F" : "rgba(255,255,255,0.18)"}`,
                transition: "all 0.2s",
              }}>
                {item.done && <span style={{ fontSize: 8, color: "#3D9E5F", fontWeight: 800, lineHeight: 1 }}>✓</span>}
              </div>
              <span style={{ fontSize: 12, color: item.done ? "var(--fg)" : "var(--fg-mute)" }}>{item.label}</span>
            </div>
          ))}
        </div>
      )}
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

      <button data-tour="new-goal-btn" type="button" onClick={onNewGoal} className="site-btn site-btn-primary" style={{ width: "100%", minHeight: 42, justifyContent: "flex-start", padding: "0 14px", fontSize: 13 }}>
        <span aria-hidden="true">＋</span>
        New goal
      </button>

      <div data-tour="workspace-sidebar" style={{ display: "grid", gap: 8 }}>
        <a href="#current-run" style={{ ...navItemStyle, color: "var(--fg)" }}>
          <span aria-hidden="true">●</span>
          Current run
        </a>
        <button type="button" onClick={onOpenPlan} style={navItemStyle}>
          <span aria-hidden="true">▣</span>
          Plan
        </button>
        <Link data-tour="nav-integrations" href="/integrations" style={navItemStyle}>
          <span aria-hidden="true">⌘</span>
          Integrations
        </Link>
        <Link data-tour="nav-outreach" href="/outreach" style={navItemStyle}>
          <span aria-hidden="true">✉</span>
          Outreach
        </Link>
        <Link data-tour="nav-payments" href="/payments" style={navItemStyle}>
          <span aria-hidden="true">$</span>
          Payments
        </Link>
        <Link href="/settings" style={navItemStyle}>
          <span aria-hidden="true">⚙</span>
          Settings
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

  const saveCache = useCallback((a: Record<string, AgentState>, p: AgentTask[], d: boolean, cn?: string, stack?: AgentStackTemplate | null, artifacts?: RunArtifactState[], saferun?: SafeRunActionState[], outcomeEvents?: OutcomeLedgerEvent[], genome?: CompanyGenomeState | null, approvals?: ApprovalQueueItemState[], operatingPlan?: StackOperatingPlan | null, manifest?: AgentDepartmentManifest | null) => {
    if (!sessionId) return;
    try { localStorage.setItem(CACHE_KEY, JSON.stringify({ agents: a, planTasks: p, done: d, autoCompanyName: cn, selectedStack: stack, runArtifacts: artifacts ?? [], safeRunActions: saferun ?? [], outcomes: outcomeEvents ?? [], companyGenome: genome ?? null, approvalQueue: approvals ?? [], stackOperatingPlan: operatingPlan ?? null, stackManifest: manifest ?? null })); } catch {}
  }, [CACHE_KEY, sessionId]);

  // Always start with empty state to avoid SSR/client hydration mismatch;
  // load localStorage cache in useEffect after mount.
  const [agents, setAgents] = useState<Record<string, AgentState>>({});
  const [planTasks, setPlanTasks] = useState<AgentTask[]>([]);
  const [activeAgent, setActiveAgent] = useState<string>("");
  const [expandedGoal, setExpandedGoal] = useState<string>("");
  const [autoCompanyName, setAutoCompanyName] = useState<string>("");
  const [done, setDone] = useState(false);
  const [sessionCost, setSessionCost] = useState<{total_tokens: number; total_cost_usd: number; cached_tokens: number} | null>(null);
  const [inputRequest, setInputRequest] = useState<InputRequest | null>(null);
  const [selectedStack, setSelectedStack] = useState<AgentStackTemplate | null>(null);
  const [runArtifacts, setRunArtifacts] = useState<RunArtifactState[]>([]);
  const [safeRunActions, setSafeRunActions] = useState<SafeRunActionState[]>([]);
  const [outcomes, setOutcomes] = useState<OutcomeLedgerEvent[]>([]);
  const [companyGenome, setCompanyGenome] = useState<CompanyGenomeState | null>(null);
  const [approvalQueue, setApprovalQueue] = useState<ApprovalQueueItemState[]>([]);
  const [stackOperatingPlan, setStackOperatingPlan] = useState<StackOperatingPlan | null>(null);
  const [stackManifest, setStackManifest] = useState<AgentDepartmentManifest | null>(null);
  const [stackReadiness, setStackReadiness] = useState<StackReadiness | null>(null);
  const [connectorCoverage, setConnectorCoverage] = useState<ConnectorCoverage | null>(null);
  const [connectorSetup, setConnectorSetup] = useState<ConnectorSetupPlan | null>(null);
  const [sessionDigest, setSessionDigest] = useState<SessionDigest | null>(null);
  const [subteamReport, setSubteamReport] = useState<SubteamReport | null>(null);
  const [sessionWorkboard, setSessionWorkboard] = useState<SessionWorkboard | null>(null);
  const [sessionState, setSessionState] = useState<SessionStateSnapshot | null>(null);
  const [selectedSubteam, setSelectedSubteam] = useState("engineering");
  const [sessionQuestion, setSessionQuestion] = useState("What did the engineering subteam do?");
  const [sessionAnswer, setSessionAnswer] = useState<SessionAnswer | null>(null);
  const [askingSession, setAskingSession] = useState(false);

  // Restore from cache after first render (client-only)
  useEffect(() => {
    if (!sessionId) return;
    try {
      const raw = localStorage.getItem(CACHE_KEY);
      if (!raw) return;
      const cached = JSON.parse(raw) as { agents: Record<string, AgentState>; planTasks: AgentTask[]; done: boolean; autoCompanyName?: string; selectedStack?: AgentStackTemplate; runArtifacts?: RunArtifactState[]; safeRunActions?: SafeRunActionState[]; outcomes?: OutcomeLedgerEvent[]; companyGenome?: CompanyGenomeState; approvalQueue?: ApprovalQueueItemState[]; stackOperatingPlan?: StackOperatingPlan; stackManifest?: AgentDepartmentManifest };
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
        if (cached.selectedStack) setSelectedStack(cached.selectedStack);
        if (cached.runArtifacts?.length) setRunArtifacts(cached.runArtifacts);
        if (cached.safeRunActions?.length) setSafeRunActions(cached.safeRunActions);
        if (cached.outcomes?.length) setOutcomes(cached.outcomes);
        if (cached.companyGenome) setCompanyGenome(cached.companyGenome);
        if (cached.approvalQueue?.length) setApprovalQueue(cached.approvalQueue);
        if (cached.stackOperatingPlan) setStackOperatingPlan(cached.stackOperatingPlan);
        if (cached.stackManifest) setStackManifest(cached.stackManifest);
        if (firstAgent) setActiveAgent(firstAgent);
      });
    } catch {}
  }, [CACHE_KEY, sessionId]);
  const [newGoalOpen, setNewGoalOpen] = useState(startNew);
  const [planOpen, setPlanOpen] = useState(false);
  const [showTour, setShowTour] = useState(false);

  // Auto-trigger tour once after onboarding
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (localStorage.getItem("astra_show_tour") !== "1") return;
    // Remove inside the callback so StrictMode's double-invoke doesn't eat the key
    const t = window.setTimeout(() => {
      localStorage.removeItem("astra_show_tour");
      setShowTour(true);
    }, 600);
    return () => window.clearTimeout(t);
  }, []);
  const [detailedNodes, setDetailedNodes] = useState<PlanNode[]>([]);
  const [pendingDetailedNodes, setPendingDetailedNodes] = useState<PlanNode[]>([]);
  const [nonResearchStarted, setNonResearchStarted] = useState(false);
  const nonResearchStartedRef = useRef(false);
  const pendingDetailedNodesRef = useRef<PlanNode[]>([]);
  useEffect(() => { nonResearchStartedRef.current = nonResearchStarted; }, [nonResearchStarted]);
  useEffect(() => { pendingDetailedNodesRef.current = pendingDetailedNodes; }, [pendingDetailedNodes]);
  useEffect(() => {
    if (startNew) queueMicrotask(() => setNewGoalOpen(true));
  }, [startNew]);
  const [error, setError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const everConnected = useRef(false);
  const notified = useRef(false);
  const errorCount = useRef(0);

  // Persist to localStorage whenever state changes
  useEffect(() => { saveCache(agents, planTasks, done, autoCompanyName, selectedStack, runArtifacts, safeRunActions, outcomes, companyGenome, approvalQueue, stackOperatingPlan, stackManifest); }, [agents, planTasks, done, autoCompanyName, selectedStack, runArtifacts, safeRunActions, outcomes, companyGenome, approvalQueue, stackOperatingPlan, stackManifest, saveCache]);

  useEffect(() => {
    if (!selectedStack?.stack_id || !founderId) return;
    let cancelled = false;
    Promise.allSettled([
      getStackReadiness(founderId, selectedStack.stack_id),
      getConnectorCoverage(founderId, selectedStack.stack_id),
      getConnectorSetup(founderId, selectedStack.stack_id),
      getStackManifest(selectedStack.stack_id, instruction, company || autoCompanyName),
    ]).then(([readinessResult, coverageResult, setupResult, manifestResult]) => {
      if (cancelled) return;
      setStackReadiness(readinessResult.status === "fulfilled" ? readinessResult.value : null);
      setConnectorCoverage(coverageResult.status === "fulfilled" ? coverageResult.value : null);
      setConnectorSetup(setupResult.status === "fulfilled" ? setupResult.value : null);
      if (manifestResult.status === "fulfilled") {
        setStackManifest(manifestResult.value);
        if (!stackOperatingPlan) setStackOperatingPlan(manifestResult.value.operating_plan);
      }
    });
    return () => { cancelled = true; };
  }, [autoCompanyName, company, founderId, instruction, selectedStack?.stack_id, stackOperatingPlan]);

  useEffect(() => {
    if (!sessionId || sessionId === "undefined") return;
    let cancelled = false;
    const loadDigest = () => {
      Promise.allSettled([getSessionDigest(sessionId), getSubteamReport(sessionId, selectedSubteam), getSessionWorkboard(sessionId), getSessionState(sessionId)])
        .then(([digestResult, reportResult, workboardResult, stateResult]) => {
          if (cancelled) return;
          if (digestResult.status === "fulfilled") setSessionDigest(digestResult.value);
          if (reportResult.status === "fulfilled") setSubteamReport(reportResult.value);
          if (workboardResult.status === "fulfilled") setSessionWorkboard(workboardResult.value);
          if (stateResult.status === "fulfilled") {
            setSessionState(stateResult.value);
            if (digestResult.status !== "fulfilled" && stateResult.value.digest) setSessionDigest(stateResult.value.digest);
            if (workboardResult.status !== "fulfilled" && stateResult.value.workboard) setSessionWorkboard(stateResult.value.workboard);
            if (!selectedStack && stateResult.value.stack) setSelectedStack(stateResult.value.stack);
            if (!stackOperatingPlan && stateResult.value.operating_plan) setStackOperatingPlan(stateResult.value.operating_plan);
            if (!stackManifest && stateResult.value.manifest) setStackManifest(stateResult.value.manifest);
            if (stateResult.value.approvals?.length) setApprovalQueue(stateResult.value.approvals as unknown as ApprovalQueueItemState[]);
          }
        });
    };
    loadDigest();
    const timer = window.setInterval(loadDigest, done ? 30000 : 8000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [done, selectedStack, selectedSubteam, sessionId, stackManifest, stackOperatingPlan]);

  useEffect(() => {
    if (!sessionId || sessionId === "undefined" || done) return;
    const es = streamGoal(sessionId);
    es.onopen = () => { setConnected(true); setReconnecting(false); errorCount.current = 0; everConnected.current = true; };
    es.onerror = () => {
      setConnected(false); errorCount.current += 1;
      if (done) { es.close(); return; }
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
      if (event.type === "stack_selected") { setSelectedStack(event.stack ?? null); return; }
      if (event.type === "stack_operating_plan" && event.operating_plan) {
        setStackOperatingPlan(event.operating_plan as StackOperatingPlan);
        return;
      }
      if (event.type === "stack_manifest" && event.manifest) {
        setStackManifest(event.manifest as AgentDepartmentManifest);
        if (event.manifest.operating_plan) setStackOperatingPlan(event.manifest.operating_plan as StackOperatingPlan);
        return;
      }
      if (event.type === "stack_approval_queue" && event.approval_queue) {
        setApprovalQueue(event.approval_queue as ApprovalQueueItemState[]);
        return;
      }
      if (event.type === "company_genome" && event.genome) {
        setCompanyGenome(event.genome as CompanyGenomeState);
        return;
      }
      if (event.type === "stack_artifact" && event.artifact) {
        setRunArtifacts(prev => {
          const nextArtifact = event.artifact as RunArtifactState;
          const rest = prev.filter(a => a.key !== nextArtifact.key);
          return [...rest, nextArtifact];
        });
        return;
      }
      if (event.type === "saferun_action" && event.action) {
        setSafeRunActions(prev => [...prev.filter(a => a.id !== event.action.id), event.action as SafeRunActionState].slice(-12));
        setApprovalQueue(prev => prev.map(item => item.key === event.action.approval_gate ? { ...item, status: "triggered", triggered_by: event.action.id } : item));
        return;
      }
      if (event.type === "saferun_result" && event.action_id) {
        setSafeRunActions(prev => prev.map(a => a.id === event.action_id ? { ...a, status: event.status, result_preview: event.result_preview } : a));
        return;
      }
      if (event.type === "stack_approval_decision" && event.gate_key && event.decision) {
        setApprovalQueue(prev => prev.map(item => item.key === event.gate_key ? { ...item, status: event.decision, note: event.note ?? null } : item));
        return;
      }
      if (event.type === "outcome_recorded" && event.outcome) {
        setOutcomes(prev => [...prev.filter(o => o.id !== event.outcome.id), event.outcome as OutcomeLedgerEvent].slice(-30));
        return;
      }
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
            next[t.agent] = { task_id: t.id, agent: t.agent, instruction: t.instruction, status: "waiting", currentAction: null, currentTool: null, lastToolAt: null, reasoning: null, model: null, tks: null, result: null, log: [], visitedUrls: [], commits: [] };
          }
          if (!activeAgent && event.tasks.length > 0) setActiveAgent(event.tasks[0].agent);
          return next;
        }

        const agent = event.agent;
        if (!agent) return next;

        const cur: AgentState = next[agent] ?? { task_id: "", agent, instruction: "", status: "waiting", currentAction: null, currentTool: null, lastToolAt: null, reasoning: null, model: null, tks: null, result: null, log: [], visitedUrls: [], commits: [] };
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
            currentAction: event.action, currentTool: event.tool ?? null, lastToolAt: Date.now(), reasoning: event.reasoning ?? null,
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
        } else if (event.type === "model_stats") {
          next[agent] = { ...cur, model: event.model ?? null, tks: event.tks ?? null };
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
        else if (event.type === "goal_error") { setError(event.error ?? "Unknown error"); setDone(true); }

        return next;
      });
    };
    return () => es.close();
  }, [sessionId, done]);

  useEffect(() => {
    if (!done || notified.current) return;
    notified.current = true;
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      new Notification("Astra — goal complete", { body: "Your company is live.", icon: "/favicon.ico" });
    }
  }, [done, sessionId]);

  // Poll session token/cost stats
  useEffect(() => {
    if (!sessionId) return;
    const fetch = () => apiFetch(`${BASE}/sessions/${sessionId}/cost`).then(r => r.json()).then(d => setSessionCost(d)).catch(() => {});
    fetch();
    if (done) return;
    const id = setInterval(fetch, 10000);
    return () => clearInterval(id);
  }, [sessionId, done]);

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
    if (!b) return a ?? { task_id: "", agent: base, instruction: "", status: "waiting", currentAction: null, currentTool: null, lastToolAt: null, reasoning: null, model: null, tks: null, result: null, log: [], visitedUrls: [], commits: [] };
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
  const outcomeValue = outcomes.reduce((sum, outcome) => sum + (Number.isFinite(outcome.value) ? outcome.value : 0), 0);
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
  const stackArtifacts: StackArtifactState[] = selectedStack?.artifacts ?? [];
  const stackApprovalGates: StackApprovalGateState[] = selectedStack?.approval_gates ?? [];
  const visibleApprovalQueue: ApprovalQueueItemState[] = approvalQueue.length ? approvalQueue : stackApprovalGates.map(gate => ({ ...gate, status: "armed", triggered_by: null }));
  const stackConnectorRequirements: StackConnectorRequirementState[] = selectedStack?.connector_requirements ?? [];
  const runArtifactByKey = new Map(runArtifacts.map(artifact => [artifact.key, artifact]));
  const artifactProgress = stackArtifacts.length
    ? Math.round((stackArtifacts.filter(a => runArtifactByKey.get(a.key)?.status === "ready" || visibleAgents[a.owner_agent]?.status === "done").length / stackArtifacts.length) * 100)
    : 0;
  const statusText = !sessionId ? "ready" : done ? "complete" : error ? "error" : reconnecting ? "reconnecting..." : connected ? "running" : "connecting";
  const handleApprovalDecision = async (gateKey: string, decision: "approved" | "skipped") => {
    setApprovalQueue(prev => prev.map(item => item.key === gateKey ? { ...item, status: decision } : item));
    try {
      await decideStackApproval(sessionId, gateKey, decision, founderId);
    } catch {
      setApprovalQueue(prev => prev.map(item => item.key === gateKey ? { ...item, status: item.triggered_by ? "triggered" : "armed" } : item));
    }
  };
  const handleAskSession = async () => {
    if (!sessionQuestion.trim()) return;
    setAskingSession(true);
    try {
      const answer = await askSession(sessionId, sessionQuestion, founderId);
      setSessionAnswer(answer);
      if (answer.report?.team) setSelectedSubteam(answer.report.team);
    } finally {
      setAskingSession(false);
    }
  };

  return (
    <div className="astra-app-layout" style={{ width: "100%", maxWidth: 1900, margin: "0 auto", display: "grid", gridTemplateColumns: "minmax(190px, 220px) minmax(0, 1fr)", gap: 24, alignItems: "stretch" }}>
      {showTour && <WorkspaceTour onDone={() => setShowTour(false)} />}
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
        {selectedStack && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-jetbrains-mono)" }}>Agent stack</span>
            <span style={{ fontSize: 13, color: "var(--fg)", fontWeight: 600 }}>{selectedStack.name}</span>
            <span style={{ fontSize: 12, color: "var(--fg-dim)" }}>{selectedStack.primary_outcome}</span>
          </div>
        )}
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

      {/* Launch checklist */}
      {sessionId && (
        <LaunchChecklist
          sessionId={sessionId}
          done={done}
          agents={visibleAgents}
          agentList={agentList}
          selectedStack={selectedStack}
        />
      )}

      {/* Agent pills + detail */}
      {agentList.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {/* Horizontal agent pill row */}
          <AgentSidebar agentList={agentList} agents={visibleAgents} activeAgent={selected} onSelect={setActiveAgent} />

          {/* Detail panel — full width */}
          {selectedState && (
            <LiquidGlass style={{ minWidth: 0 }} contentStyle={{ padding: "20px 24px", display: "flex", flexDirection: "column" }}>
              <AgentDetail state={selectedState} planTask={selectedPlanTask} sessionId={sessionId} founderId={founderId} company={company || autoCompanyName} goal={instruction} />
            </LiquidGlass>
          )}
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
              {sessionCost && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                  {[
                    ["Tokens", sessionCost.total_tokens?.toLocaleString() ?? "—"],
                    ["Cost", sessionCost.total_cost_usd != null ? `$${sessionCost.total_cost_usd.toFixed(4)}` : "—"],
                    ["Cached", sessionCost.cached_tokens != null && sessionCost.total_tokens > 0
                      ? `${Math.round(sessionCost.cached_tokens / sessionCost.total_tokens * 100)}%`
                      : "—"],
                  ].map(([label, value]) => (
                    <div key={label} style={{ padding: "11px 10px", borderRadius: 18, background: "rgba(37,99,235,0.04)", border: "1px solid rgba(37,99,235,0.12)", display: "grid", gap: 4 }}>
                      <span style={{ fontSize: 15, color: "var(--fg)", fontFamily: "var(--font-jetbrains-mono)" }}>{value}</span>
                      <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</span>
                    </div>
                  ))}
                </div>
              )}
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
                  <span style={{ fontSize: 13, color: "var(--fg)", lineHeight: 1.45 }}>{totalVisitedUrls} sites visited · {totalCommits} commits · {outcomes.length} outcomes</span>
                </div>
              </div>
              <div style={{ display: "grid", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                  <span className="site-label">Outcome ledger</span>
                  <span style={{ fontSize: 11, color: "var(--fg-mute)", fontFamily: "var(--font-jetbrains-mono)" }}>{outcomeValue} units</span>
                </div>
                {outcomes.length ? outcomes.slice(-4).reverse().map(outcome => (
                  <button
                    key={outcome.id}
                    type="button"
                    onClick={() => setActiveAgent(outcome.agent)}
                    style={{ display: "grid", gap: 3, padding: "10px 12px", borderRadius: 16, background: "rgba(61,158,95,0.06)", border: "1px solid rgba(61,158,95,0.16)", textAlign: "left" }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                      <span style={{ fontSize: 12, color: "var(--fg)" }}>{outcome.label}</span>
                      <span style={{ fontSize: 10, color: "#3D9E5F", textTransform: "uppercase", letterSpacing: "0.08em" }}>{outcome.value} {outcome.unit}</span>
                    </div>
                    <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.45 }}>{outcome.preview || AGENT_LABELS[outcome.agent] || outcome.agent}</span>
                  </button>
                )) : (
                  <div style={{ padding: "10px 12px", borderRadius: 16, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)", color: "var(--fg-mute)", fontSize: 12, lineHeight: 1.5 }}>
                    Material outputs will be counted here as agents produce leads, pages, docs, repos, and campaigns.
                  </div>
                )}
              </div>
              {sessionDigest && (
                <div style={{ display: "grid", gap: 8, borderTop: "1px solid rgba(176,180,186,0.10)", paddingTop: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                    <span className="site-label">Run digest</span>
                    <span style={{ fontSize: 11, color: sessionDigest.counts.errors ? "#C0392B" : "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {sessionDigest.counts.triggered_approvals} gates
                    </span>
                  </div>
                  <div style={{ padding: "11px 12px", borderRadius: 16, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)", display: "grid", gap: 7 }}>
                    <span style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.45 }}>{sessionDigest.summary}</span>
                    {sessionDigest.next_actions.slice(0, 3).map(action => (
                      <span key={action} style={{ fontSize: 11, color: "var(--fg)", lineHeight: 1.4 }}>- {action}</span>
                    ))}
                  </div>
                </div>
              )}
              <div style={{ display: "grid", gap: 8, borderTop: "1px solid rgba(176,180,186,0.10)", paddingTop: 12 }}>
                <span className="site-label">Ask Astra</span>
                <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8 }}>
                  <input
                    value={sessionQuestion}
                    onChange={event => setSessionQuestion(event.target.value)}
                    onKeyDown={event => { if (event.key === "Enter") void handleAskSession(); }}
                    placeholder="Ask what a subteam did or what should happen next"
                    style={{ minWidth: 0, borderRadius: 999, border: "1px solid rgba(176,180,186,0.12)", background: "rgba(255,255,255,0.035)", color: "var(--fg)", padding: "8px 11px", fontSize: 12 }}
                  />
                  <button type="button" onClick={handleAskSession} disabled={askingSession || !sessionQuestion.trim()} style={{ border: "1px solid rgba(176,180,186,0.14)", background: "rgba(255,255,255,0.06)", color: "var(--fg)", borderRadius: 999, padding: "0 12px", fontSize: 12, cursor: "pointer" }}>
                    {askingSession ? "..." : "Ask"}
                  </button>
                </div>
                {sessionAnswer && (
                  <div style={{ padding: "11px 12px", borderRadius: 16, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)", display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{sessionAnswer.answer_type.replace("_", " ")} · {Math.round(sessionAnswer.confidence * 100)}%</span>
                    {sessionAnswer.answer.split("\n").slice(0, 4).map(line => (
                      <span key={line} style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.45 }}>{line}</span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </LiquidGlass>

          <LiquidGlass contentStyle={{ padding: "26px 28px", display: "flex", flexDirection: "column", gap: 18, height: 420, minHeight: 420 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span className="site-label">Plan</span>
              <h3 style={{ fontSize: 18, margin: 0 }}>Task graph</h3>
            </div>
            <div style={{ display: "grid", gap: 10, flex: 1, minHeight: 0, overflowY: "auto", paddingRight: 4 }}>
              {stackOperatingPlan && (
                <div style={{ display: "grid", gap: 10, padding: "12px 13px", borderRadius: 18, background: "rgba(37,99,235,0.055)", border: "1px solid rgba(37,99,235,0.16)" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12, color: "var(--fg)", fontWeight: 600 }}>{stackOperatingPlan.stack_name}</span>
                    <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {stackOperatingPlan.lanes.length} lanes · {stackOperatingPlan.artifact_contract.length} artifacts
                    </span>
                  </div>
                  <span style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.45 }}>{stackOperatingPlan.operator_contract}</span>
                  <div style={{ display: "grid", gap: 7 }}>
                    {stackOperatingPlan.phases.slice(0, 4).map(phase => (
                      <div key={phase.name} style={{ display: "grid", gap: 3 }}>
                        <span style={{ fontSize: 11, color: "var(--fg)", fontWeight: 600 }}>{phase.name}</span>
                        <span style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.4 }}>{phase.objective}</span>
                      </div>
                    ))}
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <div style={{ display: "grid", gap: 3, padding: "9px 10px", borderRadius: 14, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)" }}>
                      <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Connectors</span>
                      <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.4 }}>
                        {stackOperatingPlan.connector_plan.required.length ? stackOperatingPlan.connector_plan.required.map(c => c.label).join(" · ") : "No required connectors"}
                      </span>
                    </div>
                    <div style={{ display: "grid", gap: 3, padding: "9px 10px", borderRadius: 14, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)" }}>
                      <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Approvals</span>
                      <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.4 }}>
                        {stackOperatingPlan.approval_policy.length ? stackOperatingPlan.approval_policy.map(g => g.title).slice(0, 2).join(" · ") : "No approval gates"}
                      </span>
                    </div>
                  </div>
                </div>
              )}
              {stackManifest && (
                <div style={{ display: "grid", gap: 10, padding: "12px 13px", borderRadius: 18, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                    <div style={{ display: "grid", gap: 3 }}>
                      <span className="site-label">Department manifest</span>
                      <span style={{ fontSize: 12, color: "var(--fg)", fontWeight: 600 }}>{stackManifest.department_name}</span>
                    </div>
                    <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em", whiteSpace: "nowrap" }}>
                      {stackManifest.workflow.nodes.length} lanes · {stackManifest.dashboards.length} views
                    </span>
                  </div>
                  <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.45 }}>{stackManifest.positioning}</span>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <div style={{ display: "grid", gap: 4, padding: "9px 10px", borderRadius: 14, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)" }}>
                      <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Memory</span>
                      <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.4 }}>{stackManifest.memory_policy.canonical_records.slice(0, 3).join(" · ")}</span>
                    </div>
                    <div style={{ display: "grid", gap: 4, padding: "9px 10px", borderRadius: 14, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)" }}>
                      <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Operator model</span>
                      <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.4 }}>{stackManifest.human_collaboration.default_mode}</span>
                    </div>
                  </div>
                  <div style={{ display: "grid", gap: 5 }}>
                    {stackManifest.dashboards.slice(0, 3).map(section => (
                      <div key={section.key} style={{ display: "grid", gap: 2 }}>
                        <span style={{ fontSize: 11, color: "var(--fg)", fontWeight: 600 }}>{section.title}</span>
                        <span style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.35 }}>{section.purpose}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
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
              {sessionWorkboard && (
                <div style={{ display: "grid", gap: 9, borderTop: "1px solid rgba(176,180,186,0.10)", paddingTop: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                    <span className="site-label">Workboard</span>
                    <span style={{ fontSize: 11, color: sessionWorkboard.counts.blocked ? "#D97706" : "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {sessionWorkboard.counts.founder_next} founder · {sessionWorkboard.counts.agent_next} agent
                    </span>
                  </div>
                  <div style={{ padding: "12px 13px", borderRadius: 18, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)", display: "grid", gap: 8 }}>
                    <span style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.45 }}>{sessionWorkboard.summary}</span>
                    {sessionWorkboard.items.slice(0, 5).map(item => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setActiveAgent(item.agent)}
                        style={{ display: "grid", gap: 4, padding: "9px 10px", borderRadius: 14, background: item.blockers.length ? "rgba(245,158,11,0.08)" : "rgba(255,255,255,0.025)", border: `1px solid ${item.blockers.length ? "rgba(245,158,11,0.18)" : "rgba(176,180,186,0.10)"}`, textAlign: "left" }}
                      >
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                          <span style={{ fontSize: 12, color: "var(--fg)" }}>{item.title}</span>
                          <span style={{ fontSize: 10, color: item.next_actor === "founder" ? "#D97706" : item.next_actor === "founder_review" ? "var(--fg-mute)" : "#2563EB", textTransform: "uppercase", letterSpacing: "0.08em" }}>{item.next_actor.replace("_", " ")}</span>
                        </div>
                        <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.4 }}>{item.status}{item.blockers.length ? ` · ${item.blockers[0]}` : item.summary ? ` · ${item.summary}` : ""}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {companyGenome && (
                <div style={{ display: "grid", gap: 9, borderTop: "1px solid rgba(176,180,186,0.10)", paddingTop: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                    <span className="site-label">Company genome</span>
                    <span style={{ fontSize: 11, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {companyGenome.memory.prior_context_available ? "memory linked" : "new memory"}
                    </span>
                  </div>
                  <div style={{ padding: "12px 13px", borderRadius: 18, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)", display: "grid", gap: 8 }}>
                    <span style={{ fontSize: 13, color: "var(--fg)", lineHeight: 1.45 }}>{companyGenome.stack.primary_outcome}</span>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {companyGenome.keywords.slice(0, 7).map(keyword => (
                        <span key={keyword} style={{ borderRadius: 999, border: "1px solid rgba(176,180,186,0.10)", background: "rgba(255,255,255,0.025)", padding: "4px 8px", fontSize: 10, color: "var(--fg-mute)" }}>{keyword}</span>
                      ))}
                    </div>
                    <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.45 }}>
                      {companyGenome.operating_model.agent_lanes.length} lanes · {companyGenome.operating_model.expected_artifacts.length} artifacts · {companyGenome.operating_model.approval_gates.length} approval gates
                    </span>
                  </div>
                </div>
              )}
              {subteamReport && (
                <div style={{ display: "grid", gap: 9, borderTop: "1px solid rgba(176,180,186,0.10)", paddingTop: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                    <span className="site-label">Subteam report</span>
                    <select
                      value={selectedSubteam}
                      onChange={event => setSelectedSubteam(event.target.value)}
                      style={{ borderRadius: 999, border: "1px solid rgba(176,180,186,0.14)", background: "rgba(255,255,255,0.03)", color: "var(--fg)", padding: "5px 9px", fontSize: 11 }}
                    >
                      {SUBTEAM_OPTIONS.map(team => <option key={team} value={team} style={{ background: "#0b0e14" }}>{team}</option>)}
                    </select>
                    <span style={{ fontSize: 11, color: subteamReport.blockers.length ? "#D97706" : "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {subteamReport.completed.length} done · {subteamReport.active.length} active
                    </span>
                  </div>
                  <div style={{ padding: "12px 13px", borderRadius: 18, background: "rgba(255,255,255,0.025)", border: "1px solid rgba(176,180,186,0.10)", display: "grid", gap: 8 }}>
                    <span style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.45 }}>{subteamReport.summary}</span>
                    {subteamReport.completed.slice(0, 2).map(item => (
                      <span key={`${item.agent}-${item.summary}`} style={{ fontSize: 11, color: "#3D9E5F", lineHeight: 1.4 }}>{AGENT_LABELS[item.agent] ?? item.agent}: {item.summary}</span>
                    ))}
                    {subteamReport.blockers.slice(0, 2).map(blocker => (
                      <span key={blocker} style={{ fontSize: 11, color: "#D97706", lineHeight: 1.4 }}>Blocker: {blocker}</span>
                    ))}
                    {(subteamReport.next_actions.length ? subteamReport.next_actions : [`No ${selectedSubteam} next action yet.`]).slice(0, 3).map(action => (
                      <span key={action} style={{ fontSize: 11, color: "var(--fg)", lineHeight: 1.4 }}>- {action}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </LiquidGlass>

          <LiquidGlass contentStyle={{ padding: "26px 28px", display: "flex", flexDirection: "column", gap: 18, height: 420, minHeight: 420 }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span className="site-label">Outputs</span>
                <h3 style={{ fontSize: 18, margin: 0 }}>{selectedStack ? "Stack artifacts" : "Session artifacts"}</h3>
              </div>
              <span style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", whiteSpace: "nowrap", paddingTop: 3 }}>
                {selectedStack ? `${artifactProgress}% mapped` : `${completedAgents.length} ready`}
              </span>
            </div>
            <div style={{ display: "grid", gap: 10, flex: 1, minHeight: 0, overflowY: "auto", paddingRight: 4 }}>
              {selectedStack && (
                <div style={{ padding: "13px 14px", borderRadius: 20, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(176,180,186,0.10)", display: "grid", gap: 8 }}>
                  <span style={{ fontSize: 10, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Completion rules</span>
                  {selectedStack.completion_rules.slice(0, 2).map(rule => (
                    <span key={rule} style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.45 }}>- {rule}</span>
                  ))}
                </div>
              )}
              {stackConnectorRequirements.length > 0 && (
                <div style={{ display: "grid", gap: 8 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                    <span className="site-label">Connectors</span>
                    <span style={{ fontSize: 11, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {connectorSetup ? `${connectorSetup.missing_required} missing · ${connectorSetup.connected_needs_sync} sync` : connectorCoverage ? `${connectorCoverage.coverage_score}% covered` : stackReadiness ? `${stackReadiness.connected_required}/${stackReadiness.required_total} ready` : `${stackConnectorRequirements.filter(connector => connector.required).length} required`}
                    </span>
                  </div>
                  {stackConnectorRequirements.slice(0, 5).map(connector => {
                    const setup = connectorSetup?.connectors.find(item => item.key === connector.key);
                    const coverage = connectorCoverage?.connectors.find(item => item.key === connector.key);
                    const ready = setup?.setup_status === "ready" || coverage?.coverage_status === "ready";
                    const needsSync = setup?.setup_status === "connected_needs_sync";
                    const status = setup?.setup_status ?? coverage?.coverage_status ?? (stackReadiness?.connectors.find(item => item.key === connector.key)?.connected ? "connected" : connector.required ? "required" : connector.category);
                    return (
                      <div key={connector.key} style={{ padding: "10px 12px", borderRadius: 16, background: ready ? "rgba(61,158,95,0.07)" : connector.required ? "rgba(245,158,11,0.06)" : "rgba(255,255,255,0.025)", border: `1px solid ${ready ? "rgba(61,158,95,0.18)" : connector.required ? "rgba(245,158,11,0.16)" : "rgba(176,180,186,0.10)"}`, display: "grid", gap: 5 }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                          <span style={{ fontSize: 12, color: "var(--fg)" }}>{connector.label}</span>
                          <span style={{ fontSize: 10, color: ready ? "#3D9E5F" : needsSync ? "#2F74FF" : connector.required ? "#D97706" : "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                            {status.replaceAll("_", " ")}
                          </span>
                        </div>
                        <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.45 }}>{connector.purpose}</span>
                        {setup ? (
                          <div style={{ display: "grid", gap: 2, fontSize: 10, color: "var(--fg-mute)", lineHeight: 1.35 }}>
                            <span>Credentials: {setup.missing_fields.length ? setup.missing_fields.join(", ") : "complete"}</span>
                            <span>Memory: {setup.sync.brain_record_count} records · webhook {setup.webhook.supported ? (setup.webhook.secret_configured ? "secured" : "needs secret") : "not required"}</span>
                            {setup.validation && (
                              <span>
                                Validation: {setup.validation.status.replaceAll("_", " ")} · provider {setup.validation.provider.status.replaceAll("_", " ")}
                              </span>
                            )}
                          </div>
                        ) : coverage && (
                          <span style={{ fontSize: 10, color: "var(--fg-mute)", lineHeight: 1.35 }}>
                            Brain: {coverage.brain_record_count} records
                          </span>
                        )}
                      </div>
                    );
                  })}
                  {(connectorSetup?.next_actions?.[0] || connectorCoverage?.next_actions?.[0]) && (
                    <div style={{ padding: "10px 12px", borderRadius: 16, background: "rgba(37,99,235,0.055)", border: "1px solid rgba(37,99,235,0.14)", color: "var(--fg-dim)", fontSize: 11, lineHeight: 1.45 }}>
                      {connectorSetup?.next_actions?.[0] ?? connectorCoverage?.next_actions?.[0]}
                    </div>
                  )}
                  <Link href="/integrations" className="site-btn site-btn-ghost" style={{ minHeight: 34, width: "fit-content", padding: "0 14px", fontSize: 12 }}>
                    Configure connectors -&gt;
                  </Link>
                </div>
              )}
              {stackArtifacts.length ? stackArtifacts.slice(0, 10).map((artifact) => {
                const ownerState = visibleAgents[artifact.owner_agent];
                const emittedArtifact = runArtifactByKey.get(artifact.key);
                const ready = emittedArtifact?.status === "ready" || ownerState?.status === "done";
                return (
                  <button
                    key={artifact.key}
                    type="button"
                    onClick={() => setActiveAgent(artifact.owner_agent)}
                    style={{ display: "grid", gap: 4, padding: "11px 13px", borderRadius: 18, background: ready ? "rgba(61,158,95,0.08)" : "rgba(255,255,255,0.025)", border: `1px solid ${ready ? "rgba(61,158,95,0.22)" : "rgba(176,180,186,0.10)"}`, textAlign: "left" }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                      <span style={{ fontSize: 12, color: "var(--fg)" }}>{artifact.title}</span>
                      <span style={{ fontSize: 10, color: ready ? "#3D9E5F" : "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{ready ? "ready" : AGENT_LABELS[artifact.owner_agent] ?? artifact.owner_agent}</span>
                    </div>
                    <span style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.45 }}>{emittedArtifact?.preview || artifact.description}</span>
                  </button>
                );
              }) : completedArtifacts.length ? completedArtifacts.map((item) => (
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
                  Expected artifacts will appear here after the stack is selected.
                </div>
              )}
              {visibleApprovalQueue.length > 0 && (
                <div style={{ display: "grid", gap: 8, paddingTop: 2 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                    <span className="site-label">Approval queue</span>
                    <span style={{ fontSize: 11, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {visibleApprovalQueue.filter(item => item.status === "triggered").length} triggered
                    </span>
                  </div>
                  {visibleApprovalQueue.slice(0, 4).map(gate => (
                    <div key={gate.key} style={{ padding: "10px 12px", borderRadius: 16, background: gate.status === "triggered" ? "rgba(245,158,11,0.08)" : "rgba(192,57,43,0.06)", border: `1px solid ${gate.status === "triggered" ? "rgba(245,158,11,0.20)" : "rgba(192,57,43,0.16)"}`, display: "grid", gap: 3 }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                        <span style={{ fontSize: 12, color: "var(--fg)" }}>{gate.title}</span>
                        <span style={{ fontSize: 10, color: gate.status === "triggered" ? "#D97706" : "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{gate.status}</span>
                      </div>
                      <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.45 }}>{gate.reason}</span>
                      <span style={{ fontSize: 10, color: "var(--fg-mute)", lineHeight: 1.4 }}>Before: {gate.required_before}</span>
                      {gate.status !== "approved" && gate.status !== "skipped" && (
                        <div style={{ display: "flex", gap: 7, paddingTop: 4 }}>
                          <button type="button" onClick={() => handleApprovalDecision(gate.key, "approved")} style={{ border: "1px solid rgba(61,158,95,0.22)", background: "rgba(61,158,95,0.08)", color: "#3D9E5F", borderRadius: 999, padding: "5px 10px", fontSize: 11, cursor: "pointer" }}>
                            Approve
                          </button>
                          <button type="button" onClick={() => handleApprovalDecision(gate.key, "skipped")} style={{ border: "1px solid rgba(176,180,186,0.12)", background: "rgba(255,255,255,0.025)", color: "var(--fg-mute)", borderRadius: 999, padding: "5px 10px", fontSize: 11, cursor: "pointer" }}>
                            Skip
                          </button>
                        </div>
                      )}
                      {gate.note && <span style={{ fontSize: 10, color: "var(--fg-mute)", lineHeight: 1.4 }}>Note: {gate.note}</span>}
                    </div>
                  ))}
                </div>
              )}
              {safeRunActions.length > 0 && (
                <div style={{ display: "grid", gap: 8, paddingTop: 2 }}>
                  <span className="site-label">SafeRun audit</span>
                  {safeRunActions.slice(-4).reverse().map(action => (
                    <div key={action.id} style={{ padding: "10px 12px", borderRadius: 16, background: action.risk_level === "high" ? "rgba(192,57,43,0.06)" : "rgba(245,158,11,0.06)", border: `1px solid ${action.risk_level === "high" ? "rgba(192,57,43,0.16)" : "rgba(245,158,11,0.16)"}`, display: "grid", gap: 4 }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                        <span style={{ fontSize: 12, color: "var(--fg)" }}>{TOOL_DESCRIPTIONS[action.tool] ?? action.tool}</span>
                        <span style={{ fontSize: 10, color: action.status === "executed" || action.status === "approved" ? "#3D9E5F" : action.status === "error" ? "#C0392B" : action.status === "waiting_approval" ? "#D97706" : "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{action.status.replace("_", " ")}</span>
                      </div>
                      <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.45 }}>{action.reason}</span>
                      {action.result_preview && <span style={{ fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.45 }}>{action.result_preview}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </LiquidGlass>
        </div>
      )}

      {/* Unified chat — always shown once session exists */}
      {sessionId && (
        <UnifiedChat
          sessionId={sessionId}
          founderId={founderId}
          company={company || autoCompanyName}
          goal={instruction}
          done={done}
          connected={connected}
          agents={agentList}
        />
      )}


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
