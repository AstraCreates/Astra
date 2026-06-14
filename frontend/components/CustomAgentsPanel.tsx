"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useCompany } from "@/lib/company-context";
import {
  createCustomAgent,
  deleteCustomAgent,
  getCustomAgentToolCatalog,
  listCustomAgents,
  runCustomAgent,
  updateCustomAgent,
  type CustomAgent,
  type CustomAgentInput,
  type CustomAgentToolSpec,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MODELS: { value: string; label: string }[] = [
  { value: "highoutput", label: "Powerful (best quality)" },
  { value: "small", label: "Fast (cheaper)" },
];

const CATEGORY_LABELS: Record<string, string> = {
  research: "Research & web",
  content: "Content & docs",
  design: "Design",
  memory: "Memory & knowledge",
  dashboard: "Dashboard",
  leads: "Leads",
  outreach: "Outreach / send",
  ops: "Project & ops",
};

const CONNECTOR_LABELS: Record<string, string> = {
  gmail: "Gmail",
  sendgrid: "SendGrid",
  resend: "Resend",
  linkedin: "LinkedIn",
  notion: "Notion",
  linear: "Linear",
  google_calendar: "Google Calendar",
  hunter: "Hunter.io",
};

function connectorLabel(key: string): string {
  return CONNECTOR_LABELS[key] ?? key;
}

// ---------------------------------------------------------------------------
// Modal form
// ---------------------------------------------------------------------------

interface ModalState {
  open: boolean;
  agent: CustomAgent | null;
}

function AgentModal({
  catalog,
  agent,
  onClose,
  onSave,
}: {
  catalog: CustomAgentToolSpec[];
  agent: CustomAgent | null;
  onClose: () => void;
  onSave: (input: CustomAgentInput & { clear_schedule?: boolean }) => Promise<void>;
}) {
  const [name, setName] = useState(agent?.name ?? "");
  const [role, setRole] = useState(agent?.role ?? "");
  const [toolKeys, setToolKeys] = useState<string[]>(agent?.tool_keys ?? []);
  const [model, setModel] = useState(agent?.model ?? "highoutput");
  const [scheduleOn, setScheduleOn] = useState(Boolean(agent?.schedule?.enabled));
  const [everyDays, setEveryDays] = useState(agent?.schedule?.every_days ?? 7);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const grouped = useMemo(() => {
    const out: Record<string, CustomAgentToolSpec[]> = {};
    for (const t of catalog) (out[t.category] ??= []).push(t);
    return out;
  }, [catalog]);

  // Connectors the current tool selection will require.
  const neededConnectors = useMemo(() => {
    const set = new Set<string>();
    for (const k of toolKeys) {
      const spec = catalog.find((t) => t.key === k);
      if (spec?.connector) set.add(spec.connector);
    }
    return [...set];
  }, [toolKeys, catalog]);

  function toggleTool(key: string) {
    setToolKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  }

  async function handleSubmit() {
    setErr("");
    if (!name.trim()) return setErr("Give your agent a name.");
    if (!role.trim()) return setErr("Describe what the agent should do (its prompt).");
    setSaving(true);
    try {
      await onSave({
        name: name.trim(),
        role: role.trim(),
        tool_keys: toolKeys,
        model,
        schedule: scheduleOn ? { every_days: Math.max(1, everyDays), enabled: true } : null,
        clear_schedule: !scheduleOn,
      });
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[88vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-5 border-b border-gray-100">
          <h2 className="text-lg font-semibold text-gray-900">{agent ? "Edit agent" : "New custom agent"}</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Describe the job in plain language. Pick the tools it can use. Optionally run it on a schedule.
          </p>
        </div>

        <div className="px-6 py-5 space-y-5">
          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Competitor Watcher"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Role / prompt */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">What should it do?</label>
            <textarea
              value={role}
              onChange={(e) => setRole(e.target.value)}
              rows={5}
              placeholder="e.g. Every run, search the web for what our top 3 competitors shipped recently, summarize changes, and save a short report. Flag anything that affects our positioning."
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
            />
          </div>

          {/* Tools */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-2">Tools it can use</label>
            <div className="space-y-3 max-h-64 overflow-y-auto border border-gray-100 rounded-lg p-3">
              {Object.entries(grouped).map(([cat, tools]) => (
                <div key={cat}>
                  <div className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
                    {CATEGORY_LABELS[cat] ?? cat}
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                    {tools.map((t) => (
                      <label
                        key={t.key}
                        className="flex items-start gap-2 text-sm text-gray-700 cursor-pointer hover:bg-gray-50 rounded px-1.5 py-1"
                      >
                        <input
                          type="checkbox"
                          checked={toolKeys.includes(t.key)}
                          onChange={() => toggleTool(t.key)}
                          className="mt-0.5"
                        />
                        <span>
                          {t.label}
                          {t.connector && (
                            <span className="ml-1 text-[10px] text-amber-600">needs {connectorLabel(t.connector)}</span>
                          )}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Connector warning */}
          {neededConnectors.length > 0 && (
            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              This agent needs these connected to fully work:{" "}
              <strong>{neededConnectors.map(connectorLabel).join(", ")}</strong>. Connect them in Integrations — the
              agent will still run and ask for them when needed.
            </div>
          )}

          {/* Model */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">Model</label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {MODELS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>

          {/* Schedule */}
          <div>
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input type="checkbox" checked={scheduleOn} onChange={(e) => setScheduleOn(e.target.checked)} />
              Run automatically on a schedule
            </label>
            {scheduleOn && (
              <div className="flex items-center gap-2 mt-2 text-sm text-gray-700">
                Every
                <input
                  type="number"
                  min={1}
                  value={everyDays}
                  onChange={(e) => setEveryDays(parseInt(e.target.value || "1", 10))}
                  className="w-16 px-2 py-1 border border-gray-200 rounded-lg text-center focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                day(s)
              </div>
            )}
          </div>

          {err && <div className="text-xs text-red-600">{err}</div>}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100 rounded-lg">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg disabled:opacity-50"
          >
            {saving ? "Saving…" : agent ? "Save changes" : "Create agent"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function CustomAgentsPanel() {
  const { founderId, companyId } = useCompany();
  const router = useRouter();
  const [agents, setAgents] = useState<CustomAgent[]>([]);
  const [catalog, setCatalog] = useState<CustomAgentToolSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState<ModalState>({ open: false, agent: null });
  const [runningId, setRunningId] = useState("");

  const load = useCallback(async () => {
    if (!founderId) return;
    setLoading(true);
    setError("");
    try {
      const [a, c] = await Promise.all([listCustomAgents(founderId), getCustomAgentToolCatalog()]);
      setAgents(a);
      setCatalog(c);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [founderId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave(input: CustomAgentInput & { clear_schedule?: boolean }) {
    if (modal.agent) {
      const updated = await updateCustomAgent(founderId, modal.agent.id, { ...input, company_id: companyId });
      setAgents((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
    } else {
      const created = await createCustomAgent(founderId, { ...input, company_id: companyId });
      setAgents((prev) => [created, ...prev]);
    }
  }

  async function handleDelete(agent: CustomAgent) {
    if (!confirm(`Delete "${agent.name}"?`)) return;
    await deleteCustomAgent(founderId, agent.id);
    setAgents((prev) => prev.filter((a) => a.id !== agent.id));
  }

  async function handleRun(agent: CustomAgent) {
    setRunningId(agent.id);
    try {
      const { session_id } = await runCustomAgent(founderId, agent.id, { companyId });
      router.push(`/?session=${session_id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to run");
    } finally {
      setRunningId("");
    }
  }

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="px-6 py-5 border-b border-gray-100 flex items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Custom Agents</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Build your own agents from a prompt. Pick their tools. Run them on demand or on a schedule.
          </p>
        </div>
        <button
          onClick={() => setModal({ open: true, agent: null })}
          className="flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors shrink-0"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M7 1v12M1 7h12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          New agent
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {error && <div className="text-sm text-red-600 mb-3">{error}</div>}
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div className="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : agents.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <p className="text-sm">No custom agents yet.</p>
            <p className="text-xs mt-1">Create one to automate a recurring task in your own words.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {agents.map((agent) => {
              const missing = agent.connector_status?.missing ?? [];
              return (
                <div key={agent.id} className="border border-gray-150 rounded-xl p-4 hover:border-gray-300 transition-colors">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-gray-900 truncate">{agent.name}</h3>
                        {agent.schedule?.enabled && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded-full">
                            every {agent.schedule.every_days}d
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 mt-1 line-clamp-2">{agent.role}</p>
                      <div className="flex flex-wrap gap-1 mt-2">
                        {agent.tool_keys.slice(0, 6).map((k) => {
                          const spec = catalog.find((t) => t.key === k);
                          return (
                            <span key={k} className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">
                              {spec?.label ?? k}
                            </span>
                          );
                        })}
                        {agent.tool_keys.length > 6 && (
                          <span className="text-[10px] text-gray-400">+{agent.tool_keys.length - 6}</span>
                        )}
                      </div>
                      {missing.length > 0 && (
                        <div className="text-[11px] text-amber-700 mt-2">
                          ⚠ Needs connected: {missing.map(connectorLabel).join(", ")}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        onClick={() => handleRun(agent)}
                        disabled={runningId === agent.id}
                        className="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg disabled:opacity-50"
                      >
                        {runningId === agent.id ? "Starting…" : "Run now"}
                      </button>
                      <button
                        onClick={() => setModal({ open: true, agent })}
                        className="px-2.5 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 rounded-lg"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => handleDelete(agent)}
                        className="px-2.5 py-1.5 text-xs font-medium text-red-500 hover:bg-red-50 rounded-lg"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {modal.open && (
        <AgentModal
          catalog={catalog}
          agent={modal.agent}
          onClose={() => setModal({ open: false, agent: null })}
          onSave={handleSave}
        />
      )}
    </div>
  );
}
