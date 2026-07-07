"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useSearchParams } from "next/navigation";
import {
  LibraryFile,
  ExampleFile,
  getLibraryFiles,
  getLibraryFile,
  createLibraryFile,
  updateLibraryFile,
  deleteLibraryFile,
  getExamplesLibrary,
} from "@/lib/api";
import { PdfEmbed } from "@/components/GoalWorkspace";
import { useCompany } from "@/lib/company-context";

// ── Types ──────────────────────────────────────────────────────────────────────

type TabKey = "all" | "documents" | "landing-pages" | "emails" | "templates";

const TABS: { key: TabKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "documents", label: "Documents" },
  { key: "landing-pages", label: "Landing pages" },
  { key: "emails", label: "Emails" },
  { key: "templates", label: "Templates" },
];

const DEPARTMENTS = ["All", "Research", "Marketing", "Technical", "Legal", "Ops", "Finance"] as const;
type Department = (typeof DEPARTMENTS)[number];

type UnifiedItem =
  | { kind: "file"; data: LibraryFile }
  | { kind: "template"; data: ExampleFile };

// ── Helpers ────────────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  const hrs = Math.floor(mins / 60);
  const days = Math.floor(hrs / 24);
  const weeks = Math.floor(days / 7);
  if (mins < 2) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (hrs < 24) return `${hrs}h ago`;
  if (days < 7) return `${days}d ago`;
  if (weeks < 5) return `${weeks}w ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function getFileTab(file: LibraryFile): Exclude<TabKey, "all" | "templates"> {
  const name = file.filename.toLowerCase();
  const tag = (file.source_tag || "").toLowerCase();
  if (name.includes("email") || tag.includes("email") || tag.includes("outreach")) return "emails";
  if (name.includes("landing") || tag.includes("landing")) return "landing-pages";
  return "documents";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

// ── Badges ─────────────────────────────────────────────────────────────────────

function OutputBadge() {
  return (
    <span style={{
      fontSize: 9.5, fontWeight: 700, letterSpacing: ".07em",
      padding: "2px 7px", borderRadius: 4,
      border: "1px solid rgba(125,143,255,.5)",
      color: "#7d8fff",
      flexShrink: 0, lineHeight: 1.6,
    }}>OUTPUT</span>
  );
}

function TemplateBadge() {
  return (
    <span style={{
      fontSize: 9.5, fontWeight: 700, letterSpacing: ".07em",
      padding: "2px 7px", borderRadius: 4,
      background: "rgba(125,143,255,.18)",
      color: "#a5b4fc",
      flexShrink: 0, lineHeight: 1.6,
    }}>TEMPLATE</span>
  );
}

function FileBadge() {
  return (
    <span style={{
      fontSize: 9.5, fontWeight: 700, letterSpacing: ".07em",
      padding: "2px 7px", borderRadius: 4,
      border: "1px solid rgba(255,255,255,.12)",
      color: "var(--fd)",
      flexShrink: 0, lineHeight: 1.6,
    }}>FILE</span>
  );
}

// ── Unified row ────────────────────────────────────────────────────────────────

function UnifiedRow({ item, selected, onClick }: {
  item: UnifiedItem; selected: boolean; onClick: () => void;
}) {
  const [hovered, setHovered] = useState(false);

  const rowStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 12,
    padding: "14px 30px",
    cursor: "pointer",
    borderBottom: "1px solid rgba(255,255,255,.06)",
    background: selected
      ? "rgba(125,143,255,.08)"
      : hovered ? "rgba(255,255,255,.025)" : "transparent",
    transition: "background .12s",
  };

  if (item.kind === "file") {
    const f = item.data;
    const isOutput = !!f.source_tag;
    return (
      <div onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} style={rowStyle}>
        {isOutput ? <OutputBadge /> : <FileBadge />}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 500, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {f.is_canonical && <span style={{ color: "#f59e0b", marginRight: 5, fontSize: 11 }}>★</span>}
            {f.filename}
          </div>
          <div style={{ fontSize: 12, color: "var(--fm)", marginTop: 2 }}>
            {f.source_tag ? `From ${f.source_tag}` : f.department}
          </div>
        </div>
        <div style={{ fontSize: 12, color: "var(--fd)", flexShrink: 0 }}>
          {relativeTime(f.updated_at)}
        </div>
      </div>
    );
  } else {
    const e = item.data;
    return (
      <div onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} style={rowStyle}>
        <TemplateBadge />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 500, color: "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {e.title}
          </div>
          <div style={{ fontSize: 12, color: "var(--fm)", marginTop: 2 }}>
            {e.category}{e.tags.length > 0 ? ` · ${e.tags.slice(0, 3).join(", ")}` : ""}
          </div>
        </div>
        <div style={{ fontSize: 12, color: "var(--fd)", flexShrink: 0 }}>template</div>
      </div>
    );
  }
}

// ── New file form ──────────────────────────────────────────────────────────────

function NewFileForm({ founderId, onCreated, onCancel }: {
  founderId: string; onCreated: (f: LibraryFile) => void; onCancel: () => void;
}) {
  const [filename, setFilename] = useState("");
  const [department, setDepartment] = useState("Research");
  const [isCanonical, setIsCanonical] = useState(false);
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSave() {
    if (!filename.trim()) { setError("Filename required."); return; }
    setSaving(true); setError("");
    try {
      const file = await createLibraryFile({ founder_id: founderId, department, filename: filename.trim(), content, is_canonical: isCanonical });
      onCreated(file);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create file.");
    } finally { setSaving(false); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--surface)", borderLeft: "1px solid rgba(255,255,255,.08)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 20px", borderBottom: "1px solid rgba(255,255,255,.08)" }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)" }}>New File</span>
        <button onClick={onCancel} style={{ background: "none", border: "none", color: "var(--fd)", fontSize: 20, cursor: "pointer", lineHeight: 1, padding: 0 }}>&times;</button>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", gap: 16 }}>
        {error && <div style={{ fontSize: 12, color: "#f87171", background: "rgba(248,113,113,.1)", border: "1px solid rgba(248,113,113,.2)", borderRadius: 6, padding: "8px 12px" }}>{error}</div>}
        <div>
          <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--fd)", marginBottom: 6, textTransform: "uppercase", letterSpacing: ".05em" }}>Filename</label>
          <input type="text" value={filename} onChange={e => setFilename(e.target.value)} placeholder="e.g. business_context.md" className="f-input" />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--fd)", marginBottom: 6, textTransform: "uppercase", letterSpacing: ".05em" }}>Department</label>
          <select value={department} onChange={e => setDepartment(e.target.value)} className="f-input">
            {DEPARTMENTS.filter(d => d !== "All").map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", userSelect: "none" }}>
          <input type="checkbox" checked={isCanonical} onChange={e => setIsCanonical(e.target.checked)} style={{ width: 14, height: 14, accentColor: "#7d8fff" }} />
          <span style={{ fontSize: 13, color: "var(--fg)" }}>
            <span style={{ color: "#f59e0b", marginRight: 4 }}>★</span>
            Canonical — auto-inject into agents
          </span>
        </label>
        <div>
          <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--fd)", marginBottom: 6, textTransform: "uppercase", letterSpacing: ".05em" }}>Content</label>
          <textarea value={content} onChange={e => setContent(e.target.value)} placeholder="Paste or type file content..." rows={14} className="f-ta" style={{ fontFamily: "var(--font-code), monospace", fontSize: 12 }} />
        </div>
      </div>
      <div style={{ display: "flex", gap: 10, padding: "16px 20px", borderTop: "1px solid rgba(255,255,255,.08)" }}>
        <button onClick={handleSave} disabled={saving} className="btn pri" style={{ flex: 1 }}>{saving ? "Saving..." : "Create File"}</button>
        <button onClick={onCancel} className="btn">Cancel</button>
      </div>
    </div>
  );
}

// ── File editor ────────────────────────────────────────────────────────────────

function FileEditor({ file, founderId, onUpdated, onClose, onDelete }: {
  file: LibraryFile; founderId: string; onUpdated: (f: LibraryFile) => void; onClose: () => void; onDelete: () => void;
}) {
  const [content, setContent] = useState(file.content ?? "");
  const [filename, setFilename] = useState(file.filename);
  const [department, setDepartment] = useState(file.department);
  const [isCanonical, setIsCanonical] = useState(file.is_canonical);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const [loadingContent, setLoadingContent] = useState(!file.content);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  useEffect(() => {
    if (file.content !== undefined) { setContent(file.content); setLoadingContent(false); return; }
    setLoadingContent(true);
    getLibraryFile(founderId, file.id)
      .then(full => setContent(full.content ?? ""))
      .catch(() => setError("Failed to load content."))
      .finally(() => setLoadingContent(false));
  }, [file.id, file.content, founderId]);

  async function handleSave() {
    setSaving(true); setError("");
    try {
      const updated = await updateLibraryFile(file.id, { founder_id: founderId, content, filename, department, is_canonical: isCanonical });
      setDirty(false);
      onUpdated(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save.");
    } finally { setSaving(false); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--surface)", borderLeft: "1px solid rgba(255,255,255,.08)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,.08)", minHeight: 52 }}>
        {isCanonical && <span style={{ color: "#f59e0b", fontSize: 13 }}>★</span>}
        <input
          type="text"
          value={filename}
          onChange={e => { setFilename(e.target.value); setDirty(true); }}
          style={{ flex: 1, minWidth: 0, background: "transparent", border: "none", outline: "none", fontSize: 13, fontWeight: 600, color: "var(--fg)" }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          {dirty && <span style={{ fontSize: 11, color: "var(--fd)" }}>Unsaved</span>}
          <button onClick={handleSave} disabled={saving || !dirty} className="btn pri sm" style={{ fontSize: 11 }}>{saving ? "Saving..." : "Save"}</button>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--fd)", fontSize: 18, cursor: "pointer", lineHeight: 1, padding: "0 2px" }}>&times;</button>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 16px", borderBottom: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)" }}>
        <select value={department} onChange={e => { setDepartment(e.target.value); setDirty(true); }} className="f-input" style={{ fontSize: 11, padding: "3px 8px" }}>
          {DEPARTMENTS.filter(d => d !== "All").map(d => <option key={d} value={d}>{d}</option>)}
        </select>
        <label style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer", userSelect: "none" }}>
          <input type="checkbox" checked={isCanonical} onChange={e => { setIsCanonical(e.target.checked); setDirty(true); }} style={{ width: 13, height: 13, accentColor: "#7d8fff" }} />
          <span style={{ fontSize: 11, color: "#f59e0b" }}>Auto-inject</span>
        </label>
        <span style={{ fontSize: 11, color: "var(--fd)", marginLeft: "auto" }}>{formatBytes(file.size_bytes)}</span>
        {!deleteConfirm ? (
          <button onClick={() => setDeleteConfirm(true)} style={{ background: "none", border: "none", fontSize: 11, color: "var(--fd)", cursor: "pointer", padding: 0 }}>Delete</button>
        ) : (
          <span style={{ display: "flex", gap: 6 }}>
            <button onClick={onDelete} style={{ background: "none", border: "none", fontSize: 11, color: "#f87171", cursor: "pointer", padding: 0, fontWeight: 600 }}>Confirm</button>
            <button onClick={() => setDeleteConfirm(false)} style={{ background: "none", border: "none", fontSize: 11, color: "var(--fd)", cursor: "pointer", padding: 0 }}>Cancel</button>
          </span>
        )}
      </div>
      {error && <div style={{ margin: "12px 16px 0", fontSize: 12, color: "#f87171", background: "rgba(248,113,113,.1)", border: "1px solid rgba(248,113,113,.2)", borderRadius: 6, padding: "8px 12px" }}>{error}</div>}
      <div style={{ flex: 1, padding: 16, overflow: "hidden" }}>
        {file.source_path && file.source_path.toLowerCase().endsWith(".pdf") ? (
          <PdfEmbed path={file.source_path} height={520} />
        ) : loadingContent ? (
          <div style={{ fontSize: 13, color: "var(--fd)", textAlign: "center", paddingTop: 40 }}>Loading...</div>
        ) : (
          <textarea
            value={content}
            onChange={e => { setContent(e.target.value); setDirty(true); }}
            className="f-ta"
            style={{ height: "100%", fontFamily: "var(--font-code), monospace", fontSize: 12, resize: "none" }}
            placeholder="File content..."
            spellCheck={false}
          />
        )}
      </div>
    </div>
  );
}

// ── Template viewer ────────────────────────────────────────────────────────────

function TemplateViewer({ example, onClose }: { example: ExampleFile; onClose: () => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--surface)", borderLeft: "1px solid rgba(255,255,255,.08)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,.08)" }}>
        <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".07em", padding: "2px 7px", borderRadius: 4, background: "rgba(125,143,255,.18)", color: "#a5b4fc", flexShrink: 0 }}>TEMPLATE</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)", flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{example.title}</span>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--fd)", fontSize: 18, cursor: "pointer", lineHeight: 1, padding: "0 2px", flexShrink: 0 }}>&times;</button>
      </div>
      {example.tags.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, padding: "8px 16px", borderBottom: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)" }}>
          {example.tags.map(t => (
            <span key={t} style={{ fontSize: 11, background: "rgba(255,255,255,.06)", color: "var(--fm)", padding: "2px 8px", borderRadius: 10 }}>{t}</span>
          ))}
        </div>
      )}
      <div style={{ flex: 1, padding: 16, overflow: "hidden" }}>
        <textarea
          readOnly
          value={example.content}
          style={{ width: "100%", height: "100%", fontFamily: "var(--font-code), monospace", fontSize: 12, resize: "none", background: "rgba(255,255,255,.03)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 8, padding: "12px", color: "var(--fg)", outline: "none", boxSizing: "border-box" }}
          spellCheck={false}
        />
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

interface LibraryPanelProps {
  founderId: string;
  className?: string;
}

export default function LibraryPanel({ founderId, className = "" }: LibraryPanelProps) {
  const { companyId } = useCompany();
  const searchParams = useSearchParams();
  const targetSession = searchParams.get("session");
  const didAutoSelect = useRef(false);

  const [files, setFiles] = useState<LibraryFile[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(true);
  const [filesError, setFilesError] = useState("");

  const [examples, setExamples] = useState<ExampleFile[]>([]);
  const [loadingExamples, setLoadingExamples] = useState(false);
  const [examplesLoaded, setExamplesLoaded] = useState(false);

  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [search, setSearch] = useState("");

  const [selectedFile, setSelectedFile] = useState<LibraryFile | null>(null);
  const [selectedExample, setSelectedExample] = useState<ExampleFile | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);

  const loadFiles = useCallback(async () => {
    setLoadingFiles(true); setFilesError("");
    try {
      const fetched = await getLibraryFiles(founderId);
      setFiles(fetched);
    } catch (e: unknown) {
      setFilesError(e instanceof Error ? e.message : "Failed to load files.");
    } finally { setLoadingFiles(false); }
  }, [founderId]);

  useEffect(() => { if (founderId) loadFiles(); }, [founderId, loadFiles]);

  useEffect(() => {
    if (!targetSession || didAutoSelect.current || files.length === 0) return;
    const exact = files.find(f => f.source_session_id === targetSession);
    const fallback = exact ?? [...files]
      .filter(f => !!f.source_tag)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
    if (fallback) {
      didAutoSelect.current = true;
      setSelectedFile(fallback);
      setShowNewForm(false);
    }
  }, [targetSession, files]);

  useEffect(() => {
    if (examplesLoaded) return;
    if (activeTab === "all" || activeTab === "templates") {
      setLoadingExamples(true);
      getExamplesLibrary()
        .then(data => { setExamples(data); setExamplesLoaded(true); })
        .finally(() => setLoadingExamples(false));
    }
  }, [activeTab, examplesLoaded]);

  function handleFileCreated(file: LibraryFile) {
    setFiles(prev => [file, ...prev]);
    setShowNewForm(false);
    setSelectedFile(file);
    setSelectedExample(null);
  }

  function handleFileUpdated(updated: LibraryFile) {
    setFiles(prev => prev.map(f => f.id === updated.id ? { ...f, ...updated, content: undefined } : f));
    if (selectedFile?.id === updated.id) setSelectedFile(updated);
  }

  async function handleDeleteFile() {
    if (!selectedFile) return;
    try {
      await deleteLibraryFile(founderId, selectedFile.id);
      setFiles(prev => prev.filter(f => f.id !== selectedFile.id));
      setSelectedFile(null);
    } catch (e: unknown) {
      setFilesError(e instanceof Error ? e.message : "Failed to delete.");
    }
  }

  const filteredItems: UnifiedItem[] = (() => {
    const q = search.toLowerCase();
    const items: UnifiedItem[] = [];

    if (activeTab !== "templates") {
      for (const f of files) {
        if (activeTab !== "all") {
          const cat = getFileTab(f);
          if (cat !== activeTab) continue;
        }
        if (q && !f.filename.toLowerCase().includes(q) && !(f.source_tag || "").toLowerCase().includes(q)) continue;
        items.push({ kind: "file", data: f });
      }
    }

    if (activeTab === "all" || activeTab === "templates") {
      for (const e of examples) {
        if (q && !e.title.toLowerCase().includes(q) && !e.tags.some(t => t.toLowerCase().includes(q)) && !e.category.includes(q)) continue;
        items.push({ kind: "template", data: e });
      }
    }

    return items;
  })();

  const hasDetail = showNewForm || !!selectedFile || !!selectedExample;

  function handleSelectItem(item: UnifiedItem) {
    if (item.kind === "file") {
      setSelectedFile(item.data);
      setSelectedExample(null);
    } else {
      setSelectedExample(item.data);
      setSelectedFile(null);
    }
    setShowNewForm(false);
  }

  function handleCloseDetail() {
    setSelectedFile(null);
    setSelectedExample(null);
    setShowNewForm(false);
  }

  return (
    <div className={className} style={{ display: "flex", height: "100%", background: "var(--bg)", overflow: "hidden" }}>
      {/* ── Left: list panel ── */}
      <div style={{
        display: "flex", flexDirection: "column",
        flex: hasDetail ? "0 0 380px" : "1 1 auto",
        minWidth: 0,
        borderRight: hasDetail ? "1px solid rgba(255,255,255,.08)" : "none",
        height: "100%", overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{ padding: "24px 30px 0", display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: "-.01em", color: "var(--fg)" }}>Library</h1>
          <button
            className="btn"
            style={{ fontSize: 12.5 }}
            onClick={() => { setShowNewForm(true); setSelectedFile(null); setSelectedExample(null); }}
          >
            + New File
          </button>
        </div>

        {/* Search */}
        <div style={{ padding: "16px 30px 0", flexShrink: 0 }}>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search everything Astra has made..."
            style={{
              width: "100%", boxSizing: "border-box",
              background: "rgba(255,255,255,.05)",
              border: "1px solid rgba(255,255,255,.1)",
              borderRadius: 8, padding: "9px 14px",
              fontSize: 13, color: "var(--fg)",
              outline: "none",
              transition: "border-color .12s",
            }}
            onFocus={e => { e.currentTarget.style.borderColor = "rgba(125,143,255,.6)"; }}
            onBlur={e => { e.currentTarget.style.borderColor = "rgba(255,255,255,.1)"; }}
          />
        </div>

        {/* Filter tabs */}
        <div style={{ padding: "12px 30px 0", display: "flex", gap: 6, flexShrink: 0, flexWrap: "wrap" }}>
          {TABS.map(tab => {
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                style={{
                  fontSize: 12.5, fontWeight: isActive ? 600 : 500,
                  padding: "5px 13px", borderRadius: 20,
                  border: isActive ? "1px solid rgba(125,143,255,.4)" : "1px solid rgba(255,255,255,.1)",
                  background: isActive ? "rgba(125,143,255,.16)" : "transparent",
                  color: isActive ? "#a5b4fc" : "var(--fd)",
                  cursor: "pointer",
                  transition: "all .12s",
                }}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* List */}
        <div style={{ flex: 1, overflowY: "auto", marginTop: 12 }}>
          {(loadingFiles || loadingExamples) && filteredItems.length === 0 && (
            <div style={{ fontSize: 13, color: "var(--fd)", textAlign: "center", paddingTop: 48 }}>Loading...</div>
          )}
          {filesError && (
            <div style={{ fontSize: 12, color: "#f87171", textAlign: "center", paddingTop: 32, paddingInline: 30 }}>{filesError}</div>
          )}
          {!loadingFiles && !loadingExamples && !filesError && filteredItems.length === 0 && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", padding: "48px 30px", gap: 10 }}>
              <div style={{ fontSize: 32, marginBottom: 4 }}>◈</div>
              <p style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)", margin: 0 }}>
                {search ? "No results" : "Nothing here yet"}
              </p>
              <p style={{ fontSize: 13, color: "var(--fd)", margin: 0, maxWidth: 260, lineHeight: 1.6 }}>
                {search
                  ? `No items match "${search}"`
                  : activeTab === "all"
                    ? "Upload files or run a goal — everything Astra generates lands here."
                    : `No ${activeTab.replace("-", " ")} yet.`}
              </p>
            </div>
          )}
          {filteredItems.map(item => {
            const isSelected = item.kind === "file"
              ? selectedFile?.id === item.data.id
              : selectedExample?.path === item.data.path;
            return (
              <UnifiedRow
                key={item.kind === "file" ? `f-${item.data.id}` : `t-${item.data.path}`}
                item={item}
                selected={isSelected}
                onClick={() => handleSelectItem(item)}
              />
            );
          })}
        </div>

        {/* Footer */}
        <div style={{ padding: "10px 30px", borderTop: "1px solid rgba(255,255,255,.06)", fontSize: 11, color: "var(--fd)", flexShrink: 0, display: "flex", justifyContent: "space-between" }}>
          <span>{files.filter(f => !f.source_tag).length} context · {files.filter(f => f.source_tag).length} outputs</span>
          <span>{files.filter(f => f.is_canonical).length} canonical</span>
        </div>
      </div>

      {/* ── Right: detail panel ── */}
      {hasDetail && (
        <div style={{ flex: 1, minWidth: 0, height: "100%", overflow: "hidden" }}>
          {showNewForm ? (
            <NewFileForm founderId={founderId} onCreated={handleFileCreated} onCancel={handleCloseDetail} />
          ) : selectedFile ? (
            <FileEditor
              key={selectedFile.id}
              file={selectedFile}
              founderId={founderId}
              onUpdated={handleFileUpdated}
              onClose={handleCloseDetail}
              onDelete={handleDeleteFile}
            />
          ) : selectedExample ? (
            <TemplateViewer example={selectedExample} onClose={handleCloseDetail} />
          ) : null}
        </div>
      )}
    </div>
  );
}
