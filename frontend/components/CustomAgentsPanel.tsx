"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useCompany } from "@/lib/company-context";
import PageHeader, { HeaderPrimaryBtn } from "@/components/PageHeader";
import {
  createCustomAgent,
  deleteCustomAgent,
  getCustomAgentToolCatalog,
  listCustomAgents,
  runCustomAgent,
  saveServiceCredential,
  startConnectorConnect,
  updateCustomAgent,
  type CustomAgent,
  type CustomAgentConnectorMeta,
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
  email: "Email / send",
  social: "Social posting",
  messaging: "Chat & messaging",
  ops: "Project & ops",
  crm: "CRM & marketing",
  data: "Data & files",
  advanced: "Power user",
};

const CONNECTOR_LABELS: Record<string, string> = {
  gmail: "Gmail",
  outlook: "Outlook",
  sendgrid: "email service",
  resend: "email service",
  linkedin: "LinkedIn",
  twitter: "X / Twitter",
  reddit: "Reddit",
  slack: "Slack",
  discord: "Discord",
  telegram: "Telegram",
  notion: "Notion",
  linear: "Linear",
  jira: "Jira",
  trello: "Trello",
  asana: "Asana",
  clickup: "ClickUp",
  hubspot: "HubSpot",
  mailchimp: "Mailchimp",
  airtable: "Airtable",
  googlesheets: "Google Sheets",
  googledocs: "Google Docs",
  googledrive: "Google Drive",
  google_calendar: "Google Calendar",
  calendly: "Calendly",
  zoom: "Zoom",
  dropbox: "Dropbox",
  youtube: "YouTube",
  github: "GitHub",
  hunter: "email finder",
};

const CATEGORY_ORDER = [
  "research",
  "content",
  "design",
  "memory",
  "dashboard",
  "leads",
  "email",
  "social",
  "messaging",
  "ops",
  "crm",
  "data",
  "advanced",
];

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
  const [runAtTime, setRunAtTime] = useState(() => {
    const h = agent?.schedule?.run_at_hour;
    const m = agent?.schedule?.run_at_minute;
    return h != null && m != null ? `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}` : "";
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const roleRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow the prompt textarea to fit its content (capped) instead of
  // staying a fixed height and relying on the manual drag-resize handle,
  // which was easy to mistake for "the box doesn't expand."
  const growRole = useCallback(() => {
    const el = roleRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 110), 360)}px`;
  }, []);

  useEffect(() => {
    growRole();
  }, [growRole, agent]);

  const grouped = useMemo(() => {
    const out: Record<string, CustomAgentToolSpec[]> = {};
    for (const t of catalog) (out[t.category] ??= []).push(t);
    const ordered: [string, CustomAgentToolSpec[]][] = [];
    for (const cat of CATEGORY_ORDER) if (out[cat]) ordered.push([cat, out[cat]]);
    for (const cat of Object.keys(out)) if (!CATEGORY_ORDER.includes(cat)) ordered.push([cat, out[cat]]);
    return ordered;
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
      const [runAtHour, runAtMinute] = runAtTime
        ? runAtTime.split(":").map((n) => parseInt(n, 10))
        : [null, null];
      await onSave({
        name: name.trim(),
        role: role.trim(),
        tool_keys: toolKeys,
        model,
        schedule: scheduleOn
          ? {
              every_days: Math.max(1, everyDays),
              enabled: true,
              run_at_hour: runAtHour,
              run_at_minute: runAtMinute,
            }
          : null,
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
    <div className="astra-modal-backdrop" style={{ zIndex: 50 }} onClick={onClose}>
      <div
        className="astra-modal-shell"
        style={{ maxWidth: 820 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="astra-modal-panel">
        <div className="astra-modal-header">
          <div className="astra-modal-header-row">
            <div>
              <div className="astra-modal-eyebrow">custom agents</div>
              <div className="astra-modal-title" style={{ fontSize: 24 }}>{agent ? "Edit agent" : "New custom agent"}</div>
              <p className="astra-modal-sub">
            Describe the job in plain language. Pick the tools it can use. Optionally run it on a schedule.
          </p>
            </div>
            <button onClick={onClose} className="astra-modal-close" aria-label="Close custom agent modal">×</button>
          </div>
        </div>

        <div className="astra-modal-body">
          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Competitor Watcher"
              className="f-input"
            />
          </div>

          {/* Role / prompt */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">What should it do?</label>
            <textarea
              ref={roleRef}
              value={role}
              onChange={(e) => {
                setRole(e.target.value);
                growRole();
              }}
              rows={5}
              placeholder="e.g. Every run, search the web for what our top 3 competitors shipped recently, summarize changes, and save a short report. Flag anything that affects our positioning."
              className="f-ta"
              style={{ resize: "none", overflowY: "auto" }}
            />
          </div>

          {/* Tools */}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-2">Tools it can use</label>
            <div className="space-y-3 max-h-64 overflow-y-auto border border-gray-100 rounded-lg p-3">
              {grouped.map(([cat, tools]) => (
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
              className="f-input"
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
              <div className="flex items-center gap-2 mt-2 text-sm text-gray-700 flex-wrap">
                Every
                <input
                  type="number"
                  min={1}
                  value={everyDays}
                  onChange={(e) => setEveryDays(parseInt(e.target.value || "1", 10))}
                  className="w-16 px-2 py-1 border border-gray-200 rounded-lg text-center focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                day(s) at
                <input
                  type="time"
                  value={runAtTime}
                  onChange={(e) => setRunAtTime(e.target.value)}
                  className="px-2 py-1 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <span className="text-[11px] text-gray-400">UTC{runAtTime ? "" : " · optional, defaults to whenever it ticks"}</span>
              </div>
            )}
          </div>

          {err && <div className="text-xs text-red-600">{err}</div>}
        </div>

        <div className="astra-modal-actions">
          <button onClick={onClose} className="btn">Cancel</button>
          <button onClick={handleSubmit} disabled={saving} className="btn pri">
            {saving ? "Saving…" : agent ? "Save changes" : "Create agent"}
          </button>
        </div>
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
  const [connectorsMeta, setConnectorsMeta] = useState<CustomAgentConnectorMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState<ModalState>({ open: false, agent: null });
  const [runningId, setRunningId] = useState("");
  const [connecting, setConnecting] = useState("");

  const load = useCallback(async () => {
    if (!founderId) return;
    setLoading(true);
    setError("");
    try {
      const [a, c] = await Promise.all([listCustomAgents(founderId), getCustomAgentToolCatalog()]);
      setAgents(a);
      setCatalog(c.tools);
      setConnectorsMeta(c.connectors);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [founderId]);

  async function handleConnect(connectorKey: string) {
    setConnecting(connectorKey);
    setError("");
    try {
      const res = await startConnectorConnect(founderId, connectorKey);
      if (res.kind === "composio" && res.oauth_url) {
        window.open(res.oauth_url, "_blank", "noopener");
        // Give the founder time to authorize, then refresh status.
        setTimeout(load, 4000);
      } else if (res.kind === "key") {
        const token = prompt(`Paste your ${res.label} API key / token:`);
        if (token && token.trim()) {
          await saveServiceCredential(founderId, res.connector, { token: token.trim() });
          await load();
        }
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start connect");
    } finally {
      setConnecting("");
    }
  }

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
      router.push(`/s/${session_id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to run");
    } finally {
      setRunningId("");
    }
  }

  return (
    <div className="h-full flex flex-col bg-white">
      <PageHeader
        title="Custom Agents"
        subtitle="Build your own agents from a prompt. Pick their tools. Run them on demand or on a schedule."
        actions={<HeaderPrimaryBtn label="+ New Agent" onClick={() => setModal({ open: true, agent: null })} />}
      />

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
                <div key={agent.id} className="border border-gray-200 rounded-xl p-4 hover:border-gray-300 transition-colors">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <div className="text-sm font-semibold text-gray-900 truncate">{agent.name}</div>
                        {agent.schedule?.enabled && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded-full">
                            every {agent.schedule.every_days}d
                            {agent.schedule.run_at_hour != null && agent.schedule.run_at_minute != null
                              ? ` at ${String(agent.schedule.run_at_hour).padStart(2, "0")}:${String(agent.schedule.run_at_minute).padStart(2, "0")} UTC`
                              : ""}
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
                        <div className="flex flex-wrap items-center gap-1.5 mt-2">
                          <span className="text-[11px] text-amber-700">⚠ Needs:</span>
                          {missing.map((m) => {
                            const meta = connectorsMeta.find((c) => c.key === m);
                            return (
                              <button
                                key={m}
                                onClick={() => handleConnect(m)}
                                disabled={connecting === m}
                                className="text-[11px] px-2 py-0.5 border border-amber-300 text-amber-700 hover:bg-amber-50 rounded-full disabled:opacity-50"
                              >
                                {connecting === m ? "Connecting…" : `Connect ${meta?.label ?? connectorLabel(m)}`}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        onClick={() => handleRun(agent)}
                        disabled={runningId === agent.id}
                        className="btn pri sm"
                      >
                        {runningId === agent.id ? "Starting…" : "Run now"}
                      </button>
                      <button
                        onClick={() => setModal({ open: true, agent })}
                        className="btn sm"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => handleDelete(agent)}
                        className="btn danger sm"
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
