"use client";

import { useEffect, useState, useCallback } from "react";
import {
  LibraryFile,
  getLibraryFiles,
  getLibraryFile,
  createLibraryFile,
  updateLibraryFile,
  deleteLibraryFile,
} from "@/lib/api";

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

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function DeptBadge({ department }: { department: string }) {
  const cls = DEPT_COLORS[department] ?? "bg-gray-50 text-gray-700 border-gray-200";
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${cls}`}
    >
      {department}
    </span>
  );
}

interface FileRowProps {
  file: LibraryFile;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

function FileRow({ file, selected, onSelect, onDelete }: FileRowProps) {
  return (
    <div
      onClick={onSelect}
      className={`group flex items-start gap-3 px-4 py-3 cursor-pointer border-b border-[#E5E7EB] transition-colors ${
        selected ? "bg-blue-50" : "hover:bg-gray-50"
      }`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-1">
          {file.is_canonical && (
            <span title="Auto-injected into agent context" className="text-amber-500 text-sm leading-none">
              &#9733;
            </span>
          )}
          <span className="text-sm font-medium text-[#111827] truncate">{file.filename}</span>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <DeptBadge department={file.department} />
          {file.is_canonical && (
            <span className="text-xs text-amber-600 font-medium">Auto-injected</span>
          )}
        </div>
        <div className="flex items-center gap-3 mt-1 text-xs text-gray-400">
          <span>{formatDate(file.updated_at)}</span>
          <span>{formatBytes(file.size_bytes)}</span>
        </div>
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-red-500 text-sm px-1 py-0.5 rounded"
        title="Delete file"
      >
        &#128465;
      </button>
    </div>
  );
}

// ── New File Form ──────────────────────────────────────────────────────────────

interface NewFileFormProps {
  founderId: string;
  onCreated: (file: LibraryFile) => void;
  onCancel: () => void;
}

function NewFileForm({ founderId, onCreated, onCancel }: NewFileFormProps) {
  const [filename, setFilename] = useState("");
  const [department, setDepartment] = useState("Research");
  const [isCanonical, setIsCanonical] = useState(false);
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSave() {
    if (!filename.trim()) {
      setError("Filename is required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const file = await createLibraryFile({
        founder_id: founderId,
        department,
        filename: filename.trim(),
        content,
        is_canonical: isCanonical,
      });
      onCreated(file);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create file.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-5 py-4 border-b border-[#E5E7EB]">
        <h3 className="text-sm font-semibold text-[#111827]">New File</h3>
        <button
          onClick={onCancel}
          className="text-gray-400 hover:text-gray-600 text-lg leading-none"
        >
          &times;
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        {error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
            {error}
          </div>
        )}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Filename</label>
          <input
            type="text"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            placeholder="e.g. business_context.md"
            className="w-full text-sm border border-[#E5E7EB] rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#002EFF] focus:border-transparent"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Department</label>
          <select
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
            className="w-full text-sm border border-[#E5E7EB] rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#002EFF] bg-white"
          >
            {DEPARTMENTS.filter((d) => d !== "All").map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <input
            id="is-canonical"
            type="checkbox"
            checked={isCanonical}
            onChange={(e) => setIsCanonical(e.target.checked)}
            className="w-4 h-4 rounded border-gray-300 text-[#002EFF] focus:ring-[#002EFF]"
          />
          <label htmlFor="is-canonical" className="text-sm text-[#111827] select-none">
            <span className="text-amber-500 mr-1">&#9733;</span>
            Canonical — auto-inject into agent context
          </label>
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-500 mb-1">Content</label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Paste or type file content..."
            rows={14}
            className="w-full text-sm font-mono border border-[#E5E7EB] rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#002EFF] focus:border-transparent resize-none"
          />
        </div>
      </div>
      <div className="flex items-center gap-3 px-5 py-4 border-t border-[#E5E7EB]">
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex-1 bg-[#002EFF] hover:bg-[#0024CC] disabled:opacity-50 text-white text-sm font-medium rounded px-4 py-2 transition-colors"
        >
          {saving ? "Saving..." : "Create File"}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 border border-[#E5E7EB] rounded transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── File Editor ────────────────────────────────────────────────────────────────

interface FileEditorProps {
  file: LibraryFile;
  founderId: string;
  onUpdated: (file: LibraryFile) => void;
  onClose: () => void;
}

function FileEditor({ file, founderId, onUpdated, onClose }: FileEditorProps) {
  const [content, setContent] = useState(file.content ?? "");
  const [filename, setFilename] = useState(file.filename);
  const [department, setDepartment] = useState(file.department);
  const [isCanonical, setIsCanonical] = useState(file.is_canonical);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const [loadingContent, setLoadingContent] = useState(!file.content);

  // Load full content if not already present
  useEffect(() => {
    if (file.content !== undefined) {
      setContent(file.content);
      setLoadingContent(false);
      return;
    }
    setLoadingContent(true);
    getLibraryFile(founderId, file.id)
      .then((full) => {
        setContent(full.content ?? "");
      })
      .catch(() => setError("Failed to load file content."))
      .finally(() => setLoadingContent(false));
  }, [file.id, file.content, founderId]);

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      const updated = await updateLibraryFile(file.id, {
        founder_id: founderId,
        content,
        filename,
        department,
        is_canonical: isCanonical,
      });
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
      <div className="flex items-center justify-between px-5 py-3 border-b border-[#E5E7EB]">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {isCanonical && (
            <span className="text-amber-500 text-base leading-none shrink-0">&#9733;</span>
          )}
          <input
            type="text"
            value={filename}
            onChange={(e) => { setFilename(e.target.value); setDirty(true); }}
            className="text-sm font-semibold text-[#111827] bg-transparent border-0 focus:outline-none focus:ring-0 min-w-0 flex-1 truncate"
          />
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {dirty && (
            <span className="text-xs text-gray-400">Unsaved</span>
          )}
          <button
            onClick={handleSave}
            disabled={saving || !dirty}
            className="bg-[#002EFF] hover:bg-[#0024CC] disabled:opacity-40 text-white text-xs font-medium rounded px-3 py-1.5 transition-colors"
          >
            {saving ? "Saving..." : "Save"}
          </button>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none px-1"
          >
            &times;
          </button>
        </div>
      </div>

      {/* Metadata bar */}
      <div className="flex items-center gap-3 px-5 py-2 border-b border-[#E5E7EB] bg-gray-50 text-xs text-gray-500 flex-wrap">
        <select
          value={department}
          onChange={(e) => { setDepartment(e.target.value); setDirty(true); }}
          className="text-xs border border-[#E5E7EB] rounded px-2 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-[#002EFF]"
        >
          {DEPARTMENTS.filter((d) => d !== "All").map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        <label className="flex items-center gap-1 cursor-pointer select-none">
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
        <div className="mx-5 mt-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
          {error}
        </div>
      )}

      <div className="flex-1 p-4 overflow-hidden">
        {loadingContent ? (
          <div className="text-sm text-gray-400 text-center pt-12">Loading content...</div>
        ) : (
          <textarea
            value={content}
            onChange={(e) => { setContent(e.target.value); setDirty(true); }}
            className="w-full h-full text-sm font-mono border border-[#E5E7EB] rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#002EFF] focus:border-transparent resize-none"
            placeholder="File content..."
            spellCheck={false}
          />
        )}
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────

interface LibraryPanelProps {
  founderId: string;
  className?: string;
}

export default function LibraryPanel({ founderId, className = "" }: LibraryPanelProps) {
  const [files, setFiles] = useState<LibraryFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeDept, setActiveDept] = useState<Department>("All");
  const [selectedFile, setSelectedFile] = useState<LibraryFile | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const loadFiles = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const fetched = await getLibraryFiles(founderId);
      setFiles(fetched);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load files.");
    } finally {
      setLoading(false);
    }
  }, [founderId]);

  useEffect(() => {
    if (founderId) loadFiles();
  }, [founderId, loadFiles]);

  const filteredFiles =
    activeDept === "All"
      ? files
      : files.filter((f) => f.department === activeDept);

  function handleFileCreated(file: LibraryFile) {
    setFiles((prev) => [file, ...prev]);
    setShowNewForm(false);
    setSelectedFile(file);
  }

  function handleFileUpdated(updated: LibraryFile) {
    setFiles((prev) => prev.map((f) => (f.id === updated.id ? { ...f, ...updated, content: undefined } : f)));
    if (selectedFile?.id === updated.id) {
      setSelectedFile(updated);
    }
  }

  async function handleDelete(fileId: string) {
    try {
      await deleteLibraryFile(founderId, fileId);
      setFiles((prev) => prev.filter((f) => f.id !== fileId));
      if (selectedFile?.id === fileId) setSelectedFile(null);
      setDeleteConfirm(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to delete file.");
    }
  }

  const showEditor = !showNewForm && selectedFile;

  return (
    <div className={`flex h-full bg-white border border-[#E5E7EB] rounded-lg overflow-hidden ${className}`}>
      {/* Left sidebar */}
      <div className="w-72 flex flex-col border-r border-[#E5E7EB] shrink-0">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#E5E7EB]">
          <h2 className="text-sm font-semibold text-[#111827]">Library</h2>
          <button
            onClick={() => { setShowNewForm(true); setSelectedFile(null); }}
            className="flex items-center gap-1 text-xs bg-[#002EFF] hover:bg-[#0024CC] text-white px-2.5 py-1.5 rounded transition-colors font-medium"
          >
            <span className="text-base leading-none">+</span>
            New File
          </button>
        </div>

        {/* Department tabs */}
        <div className="flex gap-0.5 px-3 py-2 border-b border-[#E5E7EB] overflow-x-auto scrollbar-none">
          {DEPARTMENTS.map((dept) => {
            const count =
              dept === "All"
                ? files.length
                : files.filter((f) => f.department === dept).length;
            return (
              <button
                key={dept}
                onClick={() => setActiveDept(dept)}
                className={`shrink-0 text-xs px-2.5 py-1 rounded-full transition-colors font-medium ${
                  activeDept === dept
                    ? "bg-[#002EFF] text-white"
                    : "text-gray-500 hover:text-gray-800 hover:bg-gray-100"
                }`}
              >
                {dept}
                {count > 0 && (
                  <span
                    className={`ml-1 ${
                      activeDept === dept ? "text-blue-200" : "text-gray-400"
                    }`}
                  >
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* File list */}
        <div className="flex-1 overflow-y-auto">
          {loading && (
            <div className="text-sm text-gray-400 text-center py-10">Loading...</div>
          )}
          {!loading && error && (
            <div className="text-sm text-red-500 text-center py-10 px-4">{error}</div>
          )}
          {!loading && !error && filteredFiles.length === 0 && (
            <div className="text-sm text-gray-400 text-center py-10 px-4">
              {activeDept === "All" ? "No files yet. Create one!" : `No ${activeDept} files.`}
            </div>
          )}
          {!loading &&
            filteredFiles.map((file) => (
              <div key={file.id}>
                {deleteConfirm === file.id ? (
                  <div className="px-4 py-3 border-b border-[#E5E7EB] bg-red-50">
                    <p className="text-xs text-red-700 mb-2">
                      Delete <strong>{file.filename}</strong>?
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleDelete(file.id)}
                        className="text-xs bg-red-600 hover:bg-red-700 text-white px-2.5 py-1 rounded transition-colors"
                      >
                        Delete
                      </button>
                      <button
                        onClick={() => setDeleteConfirm(null)}
                        className="text-xs text-gray-600 hover:text-gray-800 border border-gray-300 px-2.5 py-1 rounded transition-colors"
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

        {/* Footer stats */}
        <div className="px-4 py-2 border-t border-[#E5E7EB] text-xs text-gray-400 flex items-center justify-between">
          <span>{files.length} file{files.length !== 1 ? "s" : ""}</span>
          <span>
            {files.filter((f) => f.is_canonical).length} canonical
          </span>
        </div>
      </div>

      {/* Right panel: editor or new form or empty state */}
      <div className="flex-1 flex flex-col min-w-0">
        {showNewForm ? (
          <NewFileForm
            founderId={founderId}
            onCreated={handleFileCreated}
            onCancel={() => setShowNewForm(false)}
          />
        ) : showEditor ? (
          <FileEditor
            key={selectedFile.id}
            file={selectedFile}
            founderId={founderId}
            onUpdated={handleFileUpdated}
            onClose={() => setSelectedFile(null)}
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center px-8">
            <div className="text-4xl mb-4">&#128193;</div>
            <h3 className="text-sm font-semibold text-[#111827] mb-2">Select a file to edit</h3>
            <p className="text-sm text-gray-400 max-w-xs">
              Canonical files (marked with &#9733;) are automatically injected into agent system
              prompts for context.
            </p>
            <button
              onClick={() => setShowNewForm(true)}
              className="mt-6 bg-[#002EFF] hover:bg-[#0024CC] text-white text-sm font-medium px-4 py-2 rounded transition-colors"
            >
              Create First File
            </button>
          </div>
        )}
      </div>
    </div>
  );
}


