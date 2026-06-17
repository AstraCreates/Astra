"use client";

import { useEffect, useState, useCallback } from "react";
import {
  LibraryFile,
  ExampleFile,
  getLibraryFiles,
  getLibraryFile,
  createLibraryFile,
  updateLibraryFile,
  deleteLibraryFile,
  getExamplesLibrary,
  getFundingStatus,
  triggerFundingGenerate,
  type FundingKitStatus,
} from "@/lib/api";
import PageHeader, { HeaderPrimaryBtn } from "@/components/PageHeader";
import { PdfEmbed } from "@/components/GoalWorkspace";
import { useCompany } from "@/lib/company-context";

// ── Types ──────────────────────────────────────────────────────────────────────

const DEPARTMENTS = ["All", "Research", "Marketing", "Technical", "Legal", "Ops", "Finance"] as const;
type Department = (typeof DEPARTMENTS)[number];

const DEPT_COLORS: Record<string, string> = {
  Research: "bg-blue-50 text-blue-700 border-blue-200",
  Marketing: "bg-purple-50 text-purple-700 border-purple-200",
  Technical: "bg-green-50 text-green-700 border-green-200",
  Legal: "bg-red-50 text-red-700 border-red-200",
  Ops: "bg-yellow-50 text-yellow-700 border-yellow-200",
  Finance: "bg-orange-50 text-orange-700 border-orange-200",
};

const CAT_COLORS: Record<string, string> = {
  auth: "bg-indigo-50 text-indigo-700 border-indigo-200",
  payments: "bg-green-50 text-green-700 border-green-200",
  database: "bg-blue-50 text-blue-700 border-blue-200",
  deployment: "bg-orange-50 text-orange-700 border-orange-200",
  design: "bg-pink-50 text-pink-700 border-pink-200",
  email: "bg-purple-50 text-purple-700 border-purple-200",
  legal: "bg-red-50 text-red-700 border-red-200",
  marketing: "bg-yellow-50 text-yellow-700 border-yellow-200",
  research: "bg-cyan-50 text-cyan-700 border-cyan-200",
  sales: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

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

// ── Dept badge ─────────────────────────────────────────────────────────────────

function DeptBadge({ department }: { department: string }) {
  const cls = DEPT_COLORS[department] ?? "bg-gray-50 text-gray-700 border-gray-200";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${cls}`}>
      {department}
    </span>
  );
}

function CatBadge({ category }: { category: string }) {
  const cls = CAT_COLORS[category] ?? "bg-gray-50 text-gray-700 border-gray-200";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${cls} capitalize`}>
      {category}
    </span>
  );
}

// ── File row ───────────────────────────────────────────────────────────────────

function FileRow({
  file, selected, onSelect, onDelete,
}: {
  file: LibraryFile; selected: boolean; onSelect: () => void; onDelete: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      className={`group flex items-start gap-3 px-5 py-4 cursor-pointer border-b border-[#E5E7EB] transition-colors ${
        selected ? "bg-blue-50" : "hover:bg-gray-50"
      }`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-1.5">
          {file.is_canonical && (
            <span title="Auto-injected into agent context" className="text-amber-500 text-sm leading-none shrink-0">
              &#9733;
            </span>
          )}
          <span className="text-sm font-medium text-[#111827] truncate">{file.filename}</span>
        </div>
        <div className="flex items-center gap-2 flex-wrap mb-1.5">
          <DeptBadge department={file.department} />
          {file.source_tag && (
            <span className="text-xs text-blue-600 font-medium">⚡ {file.source_tag}</span>
          )}
          {file.is_canonical && !file.source_tag && (
            <span className="text-xs text-amber-600 font-medium">Auto-injected</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <span>{formatDate(file.updated_at)}</span>
          <span>{formatBytes(file.size_bytes)}</span>
        </div>
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onDelete(); }}
        className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-red-500 text-sm px-1.5 py-1 rounded mt-0.5"
        title="Delete file"
      >
        &#128465;
      </button>
    </div>
  );
}

// ── Template row ───────────────────────────────────────────────────────────────

function TemplateRow({
  example, selected, onSelect,
}: {
  example: ExampleFile; selected: boolean; onSelect: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      className={`flex items-start gap-3 px-5 py-4 cursor-pointer border-b border-[#E5E7EB] transition-colors ${
        selected ? "bg-blue-50" : "hover:bg-gray-50"
      }`}
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[#111827] truncate mb-1.5">{example.title}</p>
        <div className="flex items-center gap-2 flex-wrap mb-1.5">
          <CatBadge category={example.category} />
        </div>
        {example.tags.length > 0 && (
          <p className="text-xs text-gray-400 truncate">{example.tags.slice(0, 5).join(", ")}</p>
        )}
      </div>
    </div>
  );
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
    if (!filename.trim()) { setError("Filename is required."); return; }
    setSaving(true);
    setError("");
    try {
      const file = await createLibraryFile({ founder_id: founderId, department, filename: filename.trim(), content, is_canonical: isCanonical });
      onCreated(file);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create file.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-6 py-4 border-b border-[#E5E7EB]">
        <h3 className="text-sm font-semibold text-[#111827]">New File</h3>
        <button onClick={onCancel} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
        {error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</div>
        )}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1.5">Filename</label>
          <input
            type="text"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            placeholder="e.g. business_context.md"
            className="f-input"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1.5">Department</label>
          <select
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
            className="f-input"
          >
            {DEPARTMENTS.filter((d) => d !== "All").map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <label className="flex items-center gap-2.5 cursor-pointer select-none">
          <input
            id="is-canonical"
            type="checkbox"
            checked={isCanonical}
            onChange={(e) => setIsCanonical(e.target.checked)}
            className="w-4 h-4 rounded border-gray-300 text-[#002EFF] focus:ring-[#002EFF]"
          />
          <span className="text-sm text-[#111827]">
            <span className="text-amber-500 mr-1">&#9733;</span>
            Canonical — auto-inject into agent context
          </span>
        </label>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1.5">Content</label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Paste or type file content..."
            rows={14}
            className="f-ta"
            style={{ fontFamily: "var(--font-code), monospace", fontSize: 12 }}
          />
        </div>
      </div>
      <div className="flex items-center gap-3 px-6 py-4 border-t border-[#E5E7EB]">
        <button onClick={handleSave} disabled={saving} className="btn pri" style={{ flex: 1 }}>
          {saving ? "Saving..." : "Create File"}
        </button>
        <button onClick={onCancel} className="btn">Cancel</button>
      </div>
    </div>
  );
}

// ── File editor ────────────────────────────────────────────────────────────────

function FileEditor({ file, founderId, onUpdated, onClose }: {
  file: LibraryFile; founderId: string; onUpdated: (f: LibraryFile) => void; onClose: () => void;
}) {
  const [content, setContent] = useState(file.content ?? "");
  const [filename, setFilename] = useState(file.filename);
  const [department, setDepartment] = useState(file.department);
  const [isCanonical, setIsCanonical] = useState(file.is_canonical);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const [loadingContent, setLoadingContent] = useState(!file.content);

  useEffect(() => {
    if (file.content !== undefined) { setContent(file.content); setLoadingContent(false); return; }
    setLoadingContent(true);
    getLibraryFile(founderId, file.id)
      .then((full) => setContent(full.content ?? ""))
      .catch(() => setError("Failed to load file content."))
      .finally(() => setLoadingContent(false));
  }, [file.id, file.content, founderId]);

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      const updated = await updateLibraryFile(file.id, { founder_id: founderId, content, filename, department, is_canonical: isCanonical });
      setDirty(false);
      onUpdated(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-6 py-3.5 border-b border-[#E5E7EB]">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {isCanonical && <span className="text-amber-500 text-base leading-none shrink-0">&#9733;</span>}
          <input
            type="text"
            value={filename}
            onChange={(e) => { setFilename(e.target.value); setDirty(true); }}
            className="text-sm font-semibold text-[#111827] bg-transparent border-0 focus:outline-none focus:ring-0 min-w-0 flex-1"
          />
        </div>
        <div className="flex items-center gap-2.5 shrink-0">
          {dirty && <span className="text-xs text-gray-400">Unsaved</span>}
          <button
            onClick={handleSave}
            disabled={saving || !dirty}
            className="btn pri sm"
          >
            {saving ? "Saving..." : "Save"}
          </button>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none px-1">&times;</button>
        </div>
      </div>
      <div className="flex items-center gap-3 px-6 py-2.5 border-b border-[#E5E7EB] bg-gray-50 text-xs text-gray-500 flex-wrap">
        <select
          value={department}
          onChange={(e) => { setDepartment(e.target.value); setDirty(true); }}
          className="f-input"
          style={{ fontSize: 11, padding: "4px 8px" }}
        >
          {DEPARTMENTS.filter((d) => d !== "All").map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <label className="flex items-center gap-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={isCanonical}
            onChange={(e) => { setIsCanonical(e.target.checked); setDirty(true); }}
            className="w-3.5 h-3.5 rounded border-gray-300 text-[#002EFF]"
          />
          <span className="text-amber-600 font-medium">Auto-inject</span>
        </label>
        <span>{formatBytes(file.size_bytes)}</span>
        <span>Updated {formatDate(file.updated_at)}</span>
      </div>
      {error && (
        <div className="mx-6 mt-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</div>
      )}
      <div className="flex-1 p-5 overflow-hidden">
        {file.source_path && file.source_path.toLowerCase().endsWith(".pdf") ? (
          <PdfEmbed path={file.source_path} height={520} />
        ) : loadingContent ? (
          <div className="text-sm text-gray-400 text-center pt-12">Loading content...</div>
        ) : (
          <textarea
            value={content}
            onChange={(e) => { setContent(e.target.value); setDirty(true); }}
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
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-6 py-3.5 border-b border-[#E5E7EB]">
        <div className="flex items-center gap-2.5 min-w-0 flex-1">
          <CatBadge category={example.category} />
          <span className="text-sm font-semibold text-[#111827] truncate">{example.title}</span>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none px-1 shrink-0">&times;</button>
      </div>
      {example.tags.length > 0 && (
        <div className="flex items-center gap-1.5 px-6 py-2.5 border-b border-[#E5E7EB] bg-gray-50 flex-wrap">
          {example.tags.map((t) => (
            <span key={t} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{t}</span>
          ))}
        </div>
      )}
      <div className="flex-1 p-5 overflow-hidden">
        <textarea
          readOnly
          value={example.content}
          className="w-full h-full text-sm font-mono border border-[#E5E7EB] rounded-lg px-4 py-3 bg-gray-50 focus:outline-none resize-none text-gray-800"
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
  const [mode, setMode] = useState<"files" | "templates" | "funding">("files");

  // Files state
  const [files, setFiles] = useState<LibraryFile[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(true);
  const [filesError, setFilesError] = useState("");
  const [activeDept, setActiveDept] = useState<Department>("All");
  const [selectedFile, setSelectedFile] = useState<LibraryFile | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  // Templates state
  const [examples, setExamples] = useState<ExampleFile[]>([]);
  const [loadingExamples, setLoadingExamples] = useState(false);
  const [examplesLoaded, setExamplesLoaded] = useState(false);
  const [selectedExample, setSelectedExample] = useState<ExampleFile | null>(null);
  const [activeCat, setActiveCat] = useState("all");
  const [templateSearch, setTemplateSearch] = useState("");

  // Funding Kit state
  const [fundingStatus, setFundingStatus] = useState<FundingKitStatus | null>(null);
  const [fundingLoading, setFundingLoading] = useState(false);
  const [fundingTriggering, setFundingTriggering] = useState(false);
  const [fundingError, setFundingError] = useState("");
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);

  const refreshFunding = useCallback(async () => {
    if (!founderId) return;
    try {
      const s = await getFundingStatus(founderId, companyId || founderId);
      setFundingStatus(s);
    } catch {
      setFundingError("Couldn't load funding kit status.");
    } finally {
      setFundingLoading(false);
    }
  }, [founderId, companyId]);

  // Load funding status when tab activated
  useEffect(() => {
    if (mode !== "funding" || fundingStatus !== null) return;
    setFundingLoading(true);
    refreshFunding();
  }, [mode, fundingStatus, refreshFunding]);

  // Poll while generating
  useEffect(() => {
    if (!fundingStatus?.generating) return;
    const t = setInterval(refreshFunding, 4000);
    return () => clearInterval(t);
  }, [fundingStatus?.generating, refreshFunding]);

  async function handleFundingGenerate() {
    if (!founderId) return;
    setFundingTriggering(true);
    setFundingError("");
    try {
      await triggerFundingGenerate(founderId, companyId || founderId);
      await refreshFunding();
    } catch (e: unknown) {
      setFundingError(e instanceof Error ? e.message : "Failed to start generation.");
    } finally {
      setFundingTriggering(false);
    }
  }

  const loadFiles = useCallback(async () => {
    setLoadingFiles(true);
    setFilesError("");
    try {
      const fetched = await getLibraryFiles(founderId);
      setFiles(fetched);
    } catch (e: unknown) {
      setFilesError(e instanceof Error ? e.message : "Failed to load files.");
    } finally {
      setLoadingFiles(false);
    }
  }, [founderId]);

  useEffect(() => { if (founderId) loadFiles(); }, [founderId, loadFiles]);

  async function loadExamples() {
    if (examplesLoaded) return;
    setLoadingExamples(true);
    try {
      const data = await getExamplesLibrary();
      setExamples(data);
      setExamplesLoaded(true);
    } finally {
      setLoadingExamples(false);
    }
  }

  function handleModeSwitch(m: "files" | "templates" | "funding") {
    setMode(m);
    if (m === "templates") loadExamples();
  }

  const filteredFiles = activeDept === "All" ? files : files.filter((f) => f.department === activeDept);

  const exampleCategories = ["all", ...Array.from(new Set(examples.map((e) => e.category))).sort()];
  const filteredExamples = examples.filter((e) => {
    const matchCat = activeCat === "all" || e.category === activeCat;
    const q = templateSearch.toLowerCase();
    const matchSearch = !q || e.title.toLowerCase().includes(q) || e.tags.some((t) => t.includes(q)) || e.category.includes(q);
    return matchCat && matchSearch;
  });

  function handleFileCreated(file: LibraryFile) {
    setFiles((prev) => [file, ...prev]);
    setShowNewForm(false);
    setSelectedFile(file);
  }

  function handleFileUpdated(updated: LibraryFile) {
    setFiles((prev) => prev.map((f) => (f.id === updated.id ? { ...f, ...updated, content: undefined } : f)));
    if (selectedFile?.id === updated.id) setSelectedFile(updated);
  }

  async function handleDelete(fileId: string) {
    try {
      await deleteLibraryFile(founderId, fileId);
      setFiles((prev) => prev.filter((f) => f.id !== fileId));
      if (selectedFile?.id === fileId) setSelectedFile(null);
      setDeleteConfirm(null);
    } catch (e: unknown) {
      setFilesError(e instanceof Error ? e.message : "Failed to delete file.");
    }
  }

  const showEditor = mode === "files" && !showNewForm && selectedFile;
  const showTemplateViewer = mode === "templates" && selectedExample;

  return (
    <div className={`flex flex-col h-full bg-white overflow-hidden ${className}`}>
      {(() => {
        const fundingGenerating = fundingStatus?.generating || fundingTriggering;
        const fundingHasDocs = (fundingStatus?.documents?.length ?? 0) > 0;
        return (
          <PageHeader
            title="Library"
            subtitle="Files and templates injected into agent context during runs."
            actions={
              mode === "files" ? (
                <HeaderPrimaryBtn label="+ New File" onClick={() => { setShowNewForm(true); setSelectedFile(null); }} />
              ) : mode === "funding" ? (
                <HeaderPrimaryBtn
                  label={fundingGenerating ? "Generating…" : fundingHasDocs ? "Regenerate" : "Generate Kit"}
                  onClick={() => { handleFundingGenerate(); }}
                  disabled={fundingGenerating}
                />
              ) : undefined
            }
          />
        );
      })()}
      {/* Top mode switcher */}
      <div className="flex items-center gap-0 border-b border-[#E5E7EB] px-5 pt-1 shrink-0">
        {(["files", "templates", "funding"] as const).map((m) => (
          <button
            key={m}
            onClick={() => handleModeSwitch(m)}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors -mb-px ${
              mode === m
                ? "border-[#002EFF] text-[#002EFF]"
                : "border-transparent text-gray-500 hover:text-gray-800"
            }`}
          >
            {m === "files" ? "My Files" : m === "templates" ? "Templates" : "Funding Kit"}
            {m === "files" && files.length > 0 && (
              <span className={`ml-1.5 text-xs ${mode === m ? "text-blue-400" : "text-gray-400"}`}>{files.length}</span>
            )}
            {m === "templates" && examplesLoaded && examples.length > 0 && (
              <span className={`ml-1.5 text-xs ${mode === m ? "text-blue-400" : "text-gray-400"}`}>{examples.length}</span>
            )}
            {m === "funding" && fundingStatus?.needs_refresh && !fundingStatus?.generating && (
              <span className="ml-1.5 text-xs text-amber-500">●</span>
            )}
          </button>
        ))}
      </div>

      <div className="flex flex-1 min-h-0">
        {/* ── FILES MODE ── */}
        {mode === "files" && (
          <>
            {/* Left sidebar */}
            <div className="w-80 flex flex-col border-r border-[#E5E7EB] shrink-0">
              {/* Header */}
              <div className="flex items-center px-5 py-3.5 border-b border-[#E5E7EB]">
                <div className="text-sm font-semibold text-[#111827]">Files</div>
              </div>

              {/* Dept filter */}
              <div className="flex flex-wrap gap-1.5 px-4 py-3 border-b border-[#E5E7EB]">
                {DEPARTMENTS.map((dept) => {
                  const count = dept === "All" ? files.length : files.filter((f) => f.department === dept).length;
                  return (
                    <button
                      key={dept}
                      onClick={() => setActiveDept(dept)}
                      className={`text-xs px-2.5 py-1 rounded-full transition-colors font-medium ${
                        activeDept === dept
                          ? "bg-[#002EFF] text-white"
                          : "text-gray-500 hover:text-gray-800 hover:bg-gray-100"
                      }`}
                    >
                      {dept}
                      {count > 0 && (
                        <span className={`ml-1 ${activeDept === dept ? "text-blue-200" : "text-gray-400"}`}>{count}</span>
                      )}
                    </button>
                  );
                })}
              </div>

              {/* File list */}
              <div className="flex-1 overflow-y-auto">
                {loadingFiles && <div className="text-sm text-gray-400 text-center py-12">Loading...</div>}
                {!loadingFiles && filesError && <div className="text-sm text-red-500 text-center py-12 px-4">{filesError}</div>}
                {!loadingFiles && !filesError && filteredFiles.length === 0 && (
                  <div className="text-sm text-gray-400 text-center py-12 px-4">
                    {activeDept === "All" ? "No files yet. Create one!" : `No ${activeDept} files.`}
                  </div>
                )}
                {!loadingFiles && filteredFiles.map((file) => (
                  <div key={file.id}>
                    {deleteConfirm === file.id ? (
                      <div className="px-5 py-4 border-b border-[#E5E7EB] bg-red-50">
                        <p className="text-xs text-red-700 mb-3">Delete <strong>{file.filename}</strong>?</p>
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleDelete(file.id)}
                            className="text-xs bg-red-600 hover:bg-red-700 text-white px-3 py-1.5 rounded-lg transition-colors"
                          >
                            Delete
                          </button>
                          <button
                            onClick={() => setDeleteConfirm(null)}
                            className="text-xs text-gray-600 hover:text-gray-800 border border-gray-300 px-3 py-1.5 rounded-lg transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <FileRow
                        file={file}
                        selected={selectedFile?.id === file.id}
                        onSelect={() => { setSelectedFile(file); setShowNewForm(false); }}
                        onDelete={() => setDeleteConfirm(file.id)}
                      />
                    )}
                  </div>
                ))}
              </div>

              {/* Footer */}
              <div className="px-5 py-3 border-t border-[#E5E7EB] text-xs text-gray-400 flex items-center justify-between">
                <span>{files.length} file{files.length !== 1 ? "s" : ""}</span>
                <span>{files.filter((f) => f.is_canonical).length} canonical</span>
              </div>
            </div>

            {/* Right panel */}
            <div className="flex-1 flex flex-col min-w-0">
              {showNewForm ? (
                <NewFileForm founderId={founderId} onCreated={handleFileCreated} onCancel={() => setShowNewForm(false)} />
              ) : showEditor ? (
                <FileEditor
                  key={selectedFile.id}
                  file={selectedFile}
                  founderId={founderId}
                  onUpdated={handleFileUpdated}
                  onClose={() => setSelectedFile(null)}
                />
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-center px-10">
                  <div className="text-5xl mb-5">&#128193;</div>
                  <h3 className="text-sm font-semibold text-[#111827] mb-2">Select a file to edit</h3>
                  <p className="text-sm text-gray-400 max-w-xs leading-relaxed">
                    Canonical files (marked with &#9733;) are automatically injected into agent system prompts for context.
                  </p>
                  <button
                    onClick={() => setShowNewForm(true)}
                    className="mt-7 bg-[#002EFF] hover:bg-[#0024CC] text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors"
                  >
                    Create First File
                  </button>
                </div>
              )}
            </div>
          </>
        )}

        {/* ── FUNDING KIT MODE ── */}
        {mode === "funding" && (() => {
          const generating = fundingStatus?.generating || fundingTriggering;
          const needsRefresh = fundingStatus?.needs_refresh && !generating;
          const hasDocs = (fundingStatus?.documents?.length ?? 0) > 0;
          const activeDoc = fundingStatus?.documents?.find((d) => d.source_path === selectedDoc)
            ?? fundingStatus?.documents?.[0] ?? null;

          // Auto-select first doc when documents arrive
          if (hasDocs && !selectedDoc && fundingStatus?.documents?.[0]?.source_path) {
            setSelectedDoc(fundingStatus.documents[0].source_path);
          }

          return (
            <div className="flex flex-1 min-h-0">
              {/* Left sidebar */}
              <div className="w-64 flex flex-col border-r border-[#E5E7EB] shrink-0">
                <div className="px-4 py-3 border-b border-[#E5E7EB]">
                  <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Documents</div>
                  {fundingStatus?.generated_at && (
                    <div className="text-xs text-gray-400 mt-0.5">
                      {new Date(fundingStatus.generated_at).toLocaleDateString()}
                      {needsRefresh ? " · outdated" : ""}
                    </div>
                  )}
                </div>

                <div className="flex-1 overflow-y-auto py-2">
                  {fundingLoading && <div className="text-xs text-gray-400 text-center py-8">Loading…</div>}
                  {fundingError && <div className="text-xs text-red-500 px-4 py-3">{fundingError}</div>}
                  {needsRefresh && (
                    <div className="mx-3 mb-2 text-xs bg-amber-50 border border-amber-200 rounded px-3 py-2 text-amber-700">
                      Genome changed.{" "}
                      <button onClick={() => { handleFundingGenerate(); }} className="underline font-semibold">Regenerate</button>
                    </div>
                  )}
                  {generating && (
                    <div className="mx-3 mb-2 text-xs bg-blue-50 border border-blue-200 rounded px-3 py-2 text-blue-600 flex items-center gap-1.5">
                      <span className="animate-spin">⟳</span> Generating…
                    </div>
                  )}
                  {!fundingLoading && !hasDocs && !generating && (
                    <div className="flex flex-col items-center text-center px-4 py-10">
                      <div style={{ fontSize: 28, color: "#9CA3AF", marginBottom: 8 }}>◈</div>
                      <p className="text-xs font-medium text-gray-500 mb-1">No documents yet</p>
                      <p className="text-xs text-gray-400 mb-4 leading-relaxed">
                        Fill in Company Brain, then generate your kit.
                      </p>
                      <button onClick={() => { handleFundingGenerate(); }} disabled={generating} className="btn pri" style={{ fontSize: 11 }}>
                        Generate Kit
                      </button>
                    </div>
                  )}
                  {hasDocs && fundingStatus?.documents.map((doc) => (
                    <button
                      key={doc.type}
                      onClick={() => setSelectedDoc(doc.source_path)}
                      className={`w-full text-left flex items-center gap-3 px-4 py-3.5 border-b border-[#E5E7EB] transition-colors ${
                        selectedDoc === doc.source_path ? "bg-blue-50" : "hover:bg-gray-50"
                      }`}
                    >
                      <span style={{ fontSize: 18, color: "#6B7280" }}>📄</span>
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-gray-800 truncate">{doc.label}</div>
                        <div className="text-xs text-gray-400 truncate">{doc.filename}</div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Right: full-height PDF viewer */}
              <div className="flex-1 flex flex-col min-w-0 min-h-0">
                {activeDoc?.source_path ? (
                  <>
                    <div className="flex items-center gap-3 px-5 py-2.5 border-b border-[#E5E7EB] bg-gray-50 shrink-0">
                      <span className="text-xs font-medium text-gray-600 flex-1 truncate">{activeDoc.label}</span>
                      <a
                        href={`/api/files/${encodeURIComponent(activeDoc.filename)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-[#002EFF] font-medium shrink-0"
                      >
                        Download ↗
                      </a>
                    </div>
                    <div className="flex-1 min-h-0">
                      <iframe
                        src={`/api/files/${encodeURIComponent(activeDoc.filename)}`}
                        style={{ width: "100%", height: "100%", border: "none", display: "block" }}
                        title={activeDoc.label}
                      />
                    </div>
                  </>
                ) : (
                  !hasDocs ? null : (
                    <div className="flex items-center justify-center h-full text-sm text-gray-400">
                      Select a document to preview
                    </div>
                  )
                )}
              </div>
            </div>
          );
        })()}

        {/* ── TEMPLATES MODE ── */}
        {mode === "templates" && (
          <>
            {/* Left sidebar */}
            <div className="w-80 flex flex-col border-r border-[#E5E7EB] shrink-0">
              {/* Search */}
              <div className="px-4 py-3 border-b border-[#E5E7EB]">
                <input
                  type="text"
                  value={templateSearch}
                  onChange={(e) => setTemplateSearch(e.target.value)}
                  placeholder="Search templates..."
                  className="w-full text-sm border border-[#E5E7EB] rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#002EFF] focus:border-transparent"
                />
              </div>

              {/* Category filter */}
              <div className="flex flex-wrap gap-1.5 px-4 py-3 border-b border-[#E5E7EB]">
                {exampleCategories.map((cat) => {
                  const count = cat === "all" ? examples.length : examples.filter((e) => e.category === cat).length;
                  return (
                    <button
                      key={cat}
                      onClick={() => setActiveCat(cat)}
                      className={`text-xs px-2.5 py-1 rounded-full transition-colors font-medium capitalize ${
                        activeCat === cat
                          ? "bg-[#002EFF] text-white"
                          : "text-gray-500 hover:text-gray-800 hover:bg-gray-100"
                      }`}
                    >
                      {cat}
                      {count > 0 && (
                        <span className={`ml-1 ${activeCat === cat ? "text-blue-200" : "text-gray-400"}`}>{count}</span>
                      )}
                    </button>
                  );
                })}
              </div>

              {/* Template list */}
              <div className="flex-1 overflow-y-auto">
                {loadingExamples && <div className="text-sm text-gray-400 text-center py-12">Loading templates...</div>}
                {!loadingExamples && filteredExamples.length === 0 && (
                  <div className="text-sm text-gray-400 text-center py-12 px-4">No templates found.</div>
                )}
                {!loadingExamples && filteredExamples.map((ex) => (
                  <TemplateRow
                    key={ex.path}
                    example={ex}
                    selected={selectedExample?.path === ex.path}
                    onSelect={() => setSelectedExample(ex)}
                  />
                ))}
              </div>

              <div className="px-5 py-3 border-t border-[#E5E7EB] text-xs text-gray-400">
                {filteredExamples.length} of {examples.length} templates · used by agents automatically
              </div>
            </div>

            {/* Right panel */}
            <div className="flex-1 flex flex-col min-w-0">
              {showTemplateViewer ? (
                <TemplateViewer example={selectedExample} onClose={() => setSelectedExample(null)} />
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-center px-10">
                  <div className="text-5xl mb-5">&#128218;</div>
                  <h3 className="text-sm font-semibold text-[#111827] mb-2">Agent code templates</h3>
                  <p className="text-sm text-gray-400 max-w-sm leading-relaxed">
                    Agents search these templates before writing code — working patterns for auth, payments,
                    deployments, and more. Select one to view.
                  </p>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
