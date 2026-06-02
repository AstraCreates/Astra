"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  attachSkill,
  createSkill,
  deleteSkill,
  detachSkill,
  listSkills,
  updateSkill,
  type Skill,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ALL_AGENT_KEYS: string[] = [
  "design",
  "finance_fundraise",
  "finance_model",
  "legal",
  "legal_docs",
  "legal_entity",
  "legal_ip",
  "marketing",
  "marketing_content",
  "marketing_outreach",
  "marketing_paid",
  "marketing_seo",
  "ops",
  "research",
  "research_competitors",
  "research_execution",
  "research_financial",
  "research_market",
  "research_regulatory",
  "sales",
  "sales_enablement",
  "sales_pipeline",
  "technical",
  "technical_data",
  "technical_infra",
  "technical_scaffold",
  "web",
];

const AGENT_LABELS: Record<string, string> = {
  design: "Design",
  finance_fundraise: "Finance — Fundraise",
  finance_model: "Finance — Model",
  legal: "Legal",
  legal_docs: "Legal — Docs",
  legal_entity: "Legal — Entity",
  legal_ip: "Legal — IP",
  marketing: "Marketing",
  marketing_content: "Marketing — Content",
  marketing_outreach: "Marketing — Outreach",
  marketing_paid: "Marketing — Paid",
  marketing_seo: "Marketing — SEO",
  ops: "Ops",
  research: "Research",
  research_competitors: "Research — Competitors",
  research_execution: "Research — Execution",
  research_financial: "Research — Financial",
  research_market: "Research — Market",
  research_regulatory: "Research — Regulatory",
  sales: "Sales",
  sales_enablement: "Sales — Enablement",
  sales_pipeline: "Sales — Pipeline",
  technical: "Technical",
  technical_data: "Technical — Data",
  technical_infra: "Technical — Infra",
  technical_scaffold: "Technical — Scaffold",
  web: "Web",
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ModalState {
  open: boolean;
  mode: "create" | "edit";
  skill: Partial<Skill> | null;
}

interface Props {
  founderId: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function agentLabel(key: string): string {
  return AGENT_LABELS[key] ?? key;
}

function pluralAgents(keys: string[]): string {
  if (keys.length === 0) return "No agents";
  if (keys.length === 1) return agentLabel(keys[0]);
  if (keys.length <= 3) return keys.map(agentLabel).join(", ");
  return `${keys.slice(0, 2).map(agentLabel).join(", ")} +${keys.length - 2} more`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function AgentCheckboxGroup({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (keys: string[]) => void;
}) {
  function toggle(key: string) {
    if (selected.includes(key)) {
      onChange(selected.filter((k) => k !== key));
    } else {
      onChange([...selected, key]);
    }
  }

  function toggleAll() {
    if (selected.length === ALL_AGENT_KEYS.length) {
      onChange([]);
    } else {
      onChange([...ALL_AGENT_KEYS]);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
          Agents
        </span>
        <button
          type="button"
          onClick={toggleAll}
          className="text-xs text-blue-600 hover:text-blue-800 transition-colors"
        >
          {selected.length === ALL_AGENT_KEYS.length ? "Deselect all" : "Select all"}
        </button>
      </div>
      <div className="grid grid-cols-2 gap-1 max-h-48 overflow-y-auto border border-gray-200 rounded-lg p-3">
        {ALL_AGENT_KEYS.map((key) => (
          <label
            key={key}
            className="flex items-center gap-2 cursor-pointer py-1 px-1 rounded hover:bg-gray-50 select-none"
          >
            <input
              type="checkbox"
              checked={selected.includes(key)}
              onChange={() => toggle(key)}
              className="w-3.5 h-3.5 accent-blue-600 rounded"
            />
            <span className="text-xs text-gray-700">{agentLabel(key)}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill Card
// ---------------------------------------------------------------------------

function SkillCard({
  skill,
  onEdit,
  onDelete,
  onToggleAgent,
}: {
  skill: Skill;
  onEdit: (skill: Skill) => void;
  onDelete: (skill: Skill) => void;
  onToggleAgent: (skill: Skill, agentKey: string, attach: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [deleting, setDeleting] = useState(false);

  return (
    <div className="border border-gray-200 rounded-xl bg-white overflow-hidden shadow-sm hover:shadow-md transition-shadow">
      {/* Header */}
      <div className="px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold text-gray-900 text-sm">{skill.name}</h3>
              {skill.is_builtin && (
                <span className="text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-200 rounded px-1.5 py-0.5">
                  Built-in
                </span>
              )}
            </div>
            {skill.description && (
              <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{skill.description}</p>
            )}
            <p className="text-[11px] text-gray-400 mt-1">
              {pluralAgents(skill.agent_keys ?? [])}
            </p>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={() => onEdit(skill)}
              className="text-xs px-2.5 py-1.5 rounded-lg text-gray-600 hover:bg-gray-100 transition-colors font-medium"
            >
              Edit
            </button>
            <button
              onClick={async () => {
                if (!confirm(`Delete skill "${skill.name}"?`)) return;
                setDeleting(true);
                onDelete(skill);
              }}
              disabled={deleting}
              className="text-xs px-2.5 py-1.5 rounded-lg text-red-600 hover:bg-red-50 transition-colors font-medium disabled:opacity-50"
            >
              {deleting ? "..." : "Delete"}
            </button>
          </div>
        </div>

        {/* Agent toggles toggle */}
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-3 text-xs text-blue-600 hover:text-blue-800 transition-colors font-medium"
        >
          {expanded ? "Hide agents" : "Manage agents"}
        </button>
      </div>

      {/* Expanded agent attachment grid */}
      {expanded && (
        <div className="border-t border-gray-100 px-5 py-3 bg-gray-50">
          <p className="text-[11px] text-gray-400 mb-2 font-medium uppercase tracking-wide">
            Attach to agents
          </p>
          <div className="grid grid-cols-2 gap-1 max-h-52 overflow-y-auto">
            {ALL_AGENT_KEYS.map((key) => {
              const attached = (skill.agent_keys ?? []).includes(key);
              return (
                <label
                  key={key}
                  className="flex items-center gap-2 cursor-pointer py-1 px-1 rounded hover:bg-white select-none transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={attached}
                    onChange={() => onToggleAgent(skill, key, !attached)}
                    className="w-3.5 h-3.5 accent-blue-600 rounded"
                  />
                  <span className="text-xs text-gray-700">{agentLabel(key)}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}

      {/* Content preview */}
      {skill.content && (
        <div className="border-t border-gray-100 px-5 py-3 bg-gray-50">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-1">
            Content preview
          </p>
          <pre className="text-[11px] text-gray-600 whitespace-pre-wrap font-mono leading-relaxed line-clamp-4 overflow-hidden">
            {skill.content}
          </pre>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

function SkillModal({
  state,
  onClose,
  onSave,
}: {
  state: ModalState;
  onClose: () => void;
  onSave: (data: {
    name: string;
    description: string;
    content: string;
    agent_keys: string[];
  }) => Promise<void>;
}) {
  const [name, setName] = useState(state.skill?.name ?? "");
  const [description, setDescription] = useState(state.skill?.description ?? "");
  const [content, setContent] = useState(state.skill?.content ?? "");
  const [agentKeys, setAgentKeys] = useState<string[]>(state.skill?.agent_keys ?? []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await onSave({ name: name.trim(), description, content, agent_keys: agentKeys });
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/30 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Dialog */}
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] flex flex-col">
        <div className="px-6 py-5 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-900">
            {state.mode === "create" ? "New Skill" : "Edit Skill"}
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Skills are prepended to the agent system prompt when the agent runs.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">
              Name <span className="text-red-500">*</span>
            </label>
            <input
              ref={nameRef}
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Tone of voice"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">
              Description
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Short summary of what this skill does"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Content */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">
              Content (Markdown)
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={8}
              placeholder="Write the guidance to inject into the agent system prompt. Markdown supported."
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 placeholder-gray-400 font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            />
          </div>

          {/* Agent multi-select */}
          <AgentCheckboxGroup selected={agentKeys} onChange={setAgentKeys} />

          {error && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
        </form>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-60 rounded-lg transition-colors"
          >
            {saving ? "Saving..." : state.mode === "create" ? "Create skill" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function SkillsPanel({ founderId }: Props) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState<ModalState>({ open: false, mode: "create", skill: null });
  const [searchQuery, setSearchQuery] = useState("");

  const load = useCallback(async () => {
    if (!founderId) return;
    setLoading(true);
    setError("");
    try {
      const data = await listSkills(founderId);
      setSkills(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load skills");
    } finally {
      setLoading(false);
    }
  }, [founderId]);

  useEffect(() => {
    load();
  }, [load]);

  function openCreate() {
    setModal({ open: true, mode: "create", skill: null });
  }

  function openEdit(skill: Skill) {
    setModal({ open: true, mode: "edit", skill });
  }

  async function handleSave(data: {
    name: string;
    description: string;
    content: string;
    agent_keys: string[];
  }) {
    if (modal.mode === "create") {
      const skill = await createSkill(founderId, data);
      setSkills((prev) => [skill, ...prev]);
    } else if (modal.skill?.id) {
      const skill = await updateSkill(founderId, modal.skill.id, data);
      setSkills((prev) => prev.map((s) => (s.id === skill.id ? skill : s)));
    }
  }

  async function handleDelete(skill: Skill) {
    await deleteSkill(founderId, skill.id);
    setSkills((prev) => prev.filter((s) => s.id !== skill.id));
  }

  async function handleToggleAgent(skill: Skill, agentKey: string, attach: boolean) {
    const updated = attach
      ? await attachSkill(founderId, skill.id, agentKey)
      : await detachSkill(founderId, skill.id, agentKey);
    setSkills((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
  }

  const filtered = skills.filter((s) => {
    const q = searchQuery.toLowerCase();
    if (!q) return true;
    return (
      s.name.toLowerCase().includes(q) ||
      (s.description ?? "").toLowerCase().includes(q) ||
      (s.agent_keys ?? []).some((k) => k.toLowerCase().includes(q))
    );
  });

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="px-6 py-5 border-b border-gray-100 flex items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Skills</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Reusable guidance packages injected into agent system prompts.
          </p>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors shrink-0"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="shrink-0">
            <path d="M7 1v12M1 7h12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          New skill
        </button>
      </div>

      {/* Search */}
      <div className="px-6 py-3 border-b border-gray-100">
        <div className="relative">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
            width="13"
            height="13"
            viewBox="0 0 13 13"
            fill="none"
          >
            <circle cx="5.5" cy="5.5" r="4.5" stroke="currentColor" strokeWidth="1.5" />
            <path d="M9.5 9.5L12 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search skills or agents..."
            className="w-full pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-lg text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div className="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : error ? (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
            {error}{" "}
            <button onClick={load} className="underline ml-1">
              Retry
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-center">
            <div className="w-10 h-10 bg-gray-100 rounded-full flex items-center justify-center mb-3">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <path
                  d="M9 2v14M2 9h14"
                  stroke="#9CA3AF"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <p className="text-sm font-medium text-gray-600">
              {searchQuery ? "No skills match your search" : "No skills yet"}
            </p>
            {!searchQuery && (
              <p className="text-xs text-gray-400 mt-1 max-w-xs">
                Create your first skill to inject guidance into agent prompts.
              </p>
            )}
            {!searchQuery && (
              <button
                onClick={openCreate}
                className="mt-4 px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
              >
                Create skill
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map((skill) => (
              <SkillCard
                key={skill.id}
                skill={skill}
                onEdit={openEdit}
                onDelete={handleDelete}
                onToggleAgent={handleToggleAgent}
              />
            ))}
          </div>
        )}
      </div>

      {/* Modal */}
      {modal.open && (
        <SkillModal
          state={modal}
          onClose={() => setModal({ open: false, mode: "create", skill: null })}
          onSave={handleSave}
        />
      )}
    </div>
  );
}
