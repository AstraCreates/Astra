"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getWorkspace,
  getWorkspaceVault,
  type Workspace,
  type WorkspaceChapter,
  type WorkspaceVaultEntry,
} from "@/lib/api";
import SessionView from "@/components/SessionView";
import { useDevUser } from "@/lib/use-dev-user";

function ago(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 2) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function chapterStatusColor(status: string) {
  if (status === "running") return "var(--blue)";
  if (status === "done") return "var(--green)";
  if (status === "error" || status === "killed") return "var(--red)";
  return "var(--fm)";
}

function ChapterItem({
  chapter,
  active,
  onClick,
}: {
  chapter: WorkspaceChapter;
  active: boolean;
  onClick: () => void;
}) {
  const dotColor = chapterStatusColor(chapter.status);
  return (
    <div
      onClick={onClick}
      style={{
        padding: "9px 12px",
        borderRadius: 8,
        cursor: "pointer",
        background: active ? "rgba(59,130,246,.12)" : "transparent",
        border: active ? "1px solid rgba(59,130,246,.3)" : "1px solid transparent",
        transition: "background .12s",
        marginBottom: 3,
      }}
      onMouseEnter={(e) => { if (!active) (e.currentTarget as HTMLDivElement).style.background = "rgba(255,255,255,.04)"; }}
      onMouseLeave={(e) => { if (!active) (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <div style={{ width: 6, height: 6, borderRadius: "50%", background: dotColor, flexShrink: 0 }} />
        <span style={{ fontSize: 11.5, fontWeight: active ? 700 : 500, color: active ? "var(--fg)" : "var(--fd)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {chapter.name}
        </span>
      </div>
      <div style={{ fontSize: 9, color: "var(--fm)", marginTop: 3, paddingLeft: 13 }}>
        {chapter.artifact_count > 0 && `${chapter.artifact_count} artifacts · `}
        {ago(chapter.created_at)}
      </div>
    </div>
  );
}

function VaultPanel({ vault }: { vault: Record<string, WorkspaceVaultEntry> }) {
  const [selKey, setSelKey] = useState<string | null>(null);
  const entries = Object.values(vault);
  const sel = selKey ? vault[selKey] : null;

  if (!entries.length) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--fm)", fontSize: 11 }}>
        No artifacts in vault yet — run a chapter to populate it.
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Artifact list */}
      <div style={{ width: 220, borderRight: "1px solid var(--bd)", overflowY: "auto", padding: "12px 8px" }}>
        <div style={{ fontSize: 8, fontWeight: 700, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".12em", padding: "0 4px", marginBottom: 8 }}>
          Workspace Vault
        </div>
        {entries.map((e) => (
          <div
            key={e.key}
            onClick={() => setSelKey(e.key)}
            style={{
              padding: "7px 8px",
              borderRadius: 7,
              cursor: "pointer",
              background: selKey === e.key ? "rgba(59,130,246,.12)" : "transparent",
              border: selKey === e.key ? "1px solid rgba(59,130,246,.3)" : "1px solid transparent",
              marginBottom: 2,
            }}
          >
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--fg)" }}>{e.title}</div>
            <div style={{ fontSize: 9, color: "var(--fm)", marginTop: 2 }}>
              {e.history.length > 0 ? `v${e.history.length + 1} · ` : ""}{ago(e.current.updated_at)}
            </div>
          </div>
        ))}
      </div>

      {/* Selected artifact */}
      <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        {sel ? (
          <>
            <div style={{ fontFamily: "var(--font-chakra)", fontSize: 15, fontWeight: 700, color: "var(--fg)", marginBottom: 4 }}>
              {sel.title}
            </div>
            <div style={{ fontSize: 9, color: "var(--green)", marginBottom: 4 }}>
              ✓ {sel.current.agent} · {ago(sel.current.updated_at)}
              {sel.history.length > 0 && <span style={{ color: "var(--fm)", marginLeft: 8 }}>{sel.history.length} previous version{sel.history.length > 1 ? "s" : ""}</span>}
            </div>
            <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 12, lineHeight: 1.7, color: "var(--fd)", fontFamily: "inherit" }}>
              {sel.current.content || sel.current.preview || "No content stored for this artifact."}
            </pre>

            {sel.history.length > 0 && (
              <details style={{ marginTop: 20 }}>
                <summary style={{ fontSize: 10, color: "var(--fm)", cursor: "pointer", userSelect: "none" }}>
                  Version history ({sel.history.length} earlier version{sel.history.length > 1 ? "s" : ""})
                </summary>
                {[...sel.history].reverse().map((h, i) => (
                  <div key={i} style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--bd)" }}>
                    <div style={{ fontSize: 9, color: "var(--fm)", marginBottom: 6 }}>
                      v{sel.history.length - i} · {h.agent} · {ago(h.updated_at)}
                    </div>
                    <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 11, lineHeight: 1.65, color: "var(--fm)", fontFamily: "inherit" }}>
                      {h.content || h.preview || "—"}
                    </pre>
                  </div>
                ))}
              </details>
            )}
          </>
        ) : (
          <div style={{ color: "var(--fm)", fontSize: 11, paddingTop: 40, textAlign: "center" }}>
            Select an artifact to view its content and history.
          </div>
        )}
      </div>
    </div>
  );
}

export default function WorkspaceView({
  workspaceId,
  initialChapterId,
}: {
  workspaceId: string;
  initialChapterId?: string;
}) {
  const router = useRouter();
  const { userId } = useDevUser();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [activeChapterId, setActiveChapterId] = useState<string | null>(initialChapterId || null);
  const [vaultOpen, setVaultOpen] = useState(false);
  const [vault, setVault] = useState<Record<string, WorkspaceVaultEntry>>({});
  const [loading, setLoading] = useState(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadWorkspace = async () => {
    try {
      const ws = await getWorkspace(workspaceId);
      setWorkspace(ws);
      // Default to the latest chapter if none specified
      if (!activeChapterId && ws.chapters && ws.chapters.length > 0) {
        setActiveChapterId(ws.chapters[ws.chapters.length - 1].chapter_id);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  const loadVault = async () => {
    try {
      const v = await getWorkspaceVault(workspaceId);
      setVault(v);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadWorkspace();
    loadVault();
    // Poll every 10s to pick up chapter status changes
    pollRef.current = setInterval(() => {
      loadWorkspace();
      loadVault();
    }, 10000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [workspaceId]);

  const activeChapter = workspace?.chapters?.find((c) => c.chapter_id === activeChapterId) || null;

  const selectChapter = (ch: WorkspaceChapter) => {
    setActiveChapterId(ch.chapter_id);
    setVaultOpen(false);
    router.replace(`/?workspace=${workspaceId}&chapter=${ch.chapter_id}&founder=${encodeURIComponent(userId)}`);
  };

  if (loading) {
    return <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--fm)", fontSize: 11 }}>Loading workspace…</div>;
  }
  if (!workspace) {
    return <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--red)", fontSize: 11 }}>Workspace not found.</div>;
  }

  const vaultCount = Object.keys(vault).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, overflow: "hidden" }}>
      {/* Topbar */}
      <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 14px", borderBottom: "1px solid var(--bd)", background: "var(--surface)", flexShrink: 0, gap: 10 }}>
        <button
          onClick={() => router.push(`/?founder=${encodeURIComponent(userId)}`)}
          style={{ background: "none", border: "none", color: "var(--fm)", fontSize: 11, cursor: "pointer", padding: "4px 6px", borderRadius: 5, display: "flex", alignItems: "center", gap: 4 }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,.06)")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
        >
          ← All Projects
        </button>
        <div style={{ width: 1, height: 14, background: "var(--bd)" }} />
        <div style={{ fontFamily: "var(--font-chakra)", fontSize: 13, fontWeight: 700, color: "var(--fg)", flex: 1 }}>
          {workspace.company_name || workspace.name}
        </div>
        <button
          className="btn"
          style={{ fontSize: 11, padding: "5px 12px" }}
          onClick={() => router.push(`/?workspace=${workspaceId}&run=1&founder=${encodeURIComponent(userId)}`)}
        >
          + New Run
        </button>
      </div>

      <div style={{ display: "flex", flex: 1, minHeight: 0, overflow: "hidden" }}>
        {/* Sidebar */}
        <div style={{ width: 200, borderRight: "1px solid var(--bd)", display: "flex", flexDirection: "column", overflowY: "auto", flexShrink: 0, background: "var(--surface)" }}>
          {/* Chapters */}
          <div style={{ padding: "12px 8px 4px" }}>
            <div style={{ fontSize: 8, fontWeight: 700, color: "var(--fm)", textTransform: "uppercase", letterSpacing: ".12em", padding: "0 4px", marginBottom: 6 }}>Chapters</div>
            {(workspace.chapters || []).length === 0 && (
              <div style={{ fontSize: 10, color: "var(--fm)", padding: "4px 4px" }}>No chapters yet.</div>
            )}
            {[...(workspace.chapters || [])].reverse().map((ch) => (
              <ChapterItem
                key={ch.chapter_id}
                chapter={ch}
                active={ch.chapter_id === activeChapterId && !vaultOpen}
                onClick={() => selectChapter(ch)}
              />
            ))}
          </div>

          {/* Vault link */}
          <div style={{ marginTop: "auto", padding: "8px 8px 12px", borderTop: "1px solid var(--bd)" }}>
            <div
              onClick={() => setVaultOpen(true)}
              style={{
                padding: "8px 10px", borderRadius: 8, cursor: "pointer",
                background: vaultOpen ? "rgba(59,130,246,.12)" : "transparent",
                border: vaultOpen ? "1px solid rgba(59,130,246,.3)" : "1px solid transparent",
                display: "flex", alignItems: "center", gap: 7,
              }}
              onMouseEnter={(e) => { if (!vaultOpen) (e.currentTarget as HTMLDivElement).style.background = "rgba(255,255,255,.04)"; }}
              onMouseLeave={(e) => { if (!vaultOpen) (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
            >
              <span style={{ fontSize: 13 }}>🗄️</span>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: vaultOpen ? "var(--fg)" : "var(--fd)" }}>Workspace Vault</div>
                <div style={{ fontSize: 9, color: "var(--fm)" }}>{vaultCount} artifact{vaultCount !== 1 ? "s" : ""}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Main content */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
          {vaultOpen ? (
            <VaultPanel vault={vault} />
          ) : activeChapter ? (
            <SessionView key={activeChapter.session_id} sessionId={activeChapter.session_id} />
          ) : (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12 }}>
              <div style={{ fontSize: 36 }}>✦</div>
              <div style={{ fontFamily: "var(--font-chakra)", fontSize: 15, fontWeight: 700, color: "var(--fg)" }}>
                {workspace.company_name || workspace.name}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--fm)", textAlign: "center", maxWidth: 320, lineHeight: 1.6 }}>
                {workspace.goal}
              </div>
              <button className="btn pri" style={{ marginTop: 8 }} onClick={() => router.push(`/?workspace=${workspaceId}&run=1&founder=${encodeURIComponent(userId)}`)}>
                + Start first run
              </button>
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
