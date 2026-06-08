"use client";

import { useEffect, useRef, useState } from "react";
import {
  clearModelOverride,
  getModelSettings,
  setModelOverride,
} from "@/lib/api";

// â”€â”€ Agent metadata â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

type Department = "Research" | "Marketing" | "Technical" | "Legal" | "Sales" | "Finance" | "Ops";

interface AgentMeta {
  key: string;
  label: string;
  department: Department;
}

const AGENTS: AgentMeta[] = [
  // Research
  { key: "research",             label: "Market Research",        department: "Research" },
  { key: "research_competitors", label: "Competitor Intel",       department: "Research" },
  { key: "research_execution",   label: "Execution Strategy",     department: "Research" },
  { key: "research_market",      label: "Market Analysis",        department: "Research" },
  { key: "research_financial",   label: "Financial Research",     department: "Research" },
  { key: "research_regulatory",  label: "Regulatory Research",    department: "Research" },
  // Marketing
  { key: "marketing",            label: "Marketing & Social",     department: "Marketing" },
  { key: "marketing_content",    label: "Content",                department: "Marketing" },
  { key: "marketing_outreach",   label: "Outreach",               department: "Marketing" },
  { key: "marketing_seo",        label: "SEO",                    department: "Marketing" },
  { key: "marketing_paid",       label: "Paid Ads",               department: "Marketing" },
  // Technical
  { key: "technical",            label: "Technical Architecture", department: "Technical" },
  { key: "technical_scaffold",   label: "Scaffold",               department: "Technical" },
  { key: "technical_infra",      label: "Infrastructure",         department: "Technical" },
  { key: "technical_data",       label: "Data",                   department: "Technical" },
  // Legal
  { key: "legal",                label: "Legal & Compliance",     department: "Legal" },
  { key: "legal_docs",           label: "Docs",                   department: "Legal" },
  { key: "legal_entity",         label: "Entity",                 department: "Legal" },
  { key: "legal_ip",             label: "IP",                     department: "Legal" },
  // Sales
  { key: "sales",                label: "Sales & Outreach",       department: "Sales" },
  { key: "sales_pipeline",       label: "Pipeline",               department: "Sales" },
  { key: "sales_enablement",     label: "Enablement",             department: "Sales" },
  // Finance
  { key: "finance_model",        label: "Financial Model",        department: "Finance" },
  { key: "finance_fundraise",    label: "Fundraising",            department: "Finance" },
  // Web / Ops / Design (standalone)
  { key: "web",                  label: "Web & Landing Page",     department: "Technical" },
  { key: "design",               label: "Design & Brand",         department: "Ops" },
  { key: "ops",                  label: "Ops & Fundraising",      department: "Ops" },
];

const DEPARTMENT_ORDER: Department[] = [
  "Research",
  "Marketing",
  "Technical",
  "Legal",
  "Sales",
  "Finance",
  "Ops",
];

const DEPT_ICON: Record<Department, string> = {
  Research:  "â—‹",
  Marketing: "â—†",
  Technical: "â—ˆ",
  Legal:     "â—‰",
  Sales:     "â—‡",
  Finance:   "â—‘",
  Ops:       "â—Ž",
};

const DEPT_COLOR: Record<Department, string> = {
  Research:  "#002EFF",
  Marketing: "#7C3AED",
  Technical: "#059669",
  Legal:     "#DC2626",
  Sales:     "#D97706",
  Finance:   "#0891B2",
  Ops:       "#6B7280",
};

// â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function shortModelName(model: string): string {
  // strip org prefix, shorten
  const parts = model.split("/");
  return parts[parts.length - 1] ?? model;
}

// â”€â”€ Sub-components â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ModelDropdown({
  value,
  availableModels,
  onChange,
  disabled,
}: {
  value: string | null;
  availableModels: string[];
  onChange: (model: string | null) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const display = value ? shortModelName(value) : "Default";

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block", minWidth: 220 }}>
      <button
        onClick={() => !disabled && setOpen((o) => !o)}
        disabled={disabled}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 12px",
          borderRadius: 8,
          border: "1px solid #E5E7EB",
          background: value ? "#EFF6FF" : "#F9FAFB",
          color: value ? "#002EFF" : "#6B7280",
          fontSize: 12,
          fontWeight: value ? 600 : 400,
          cursor: disabled ? "default" : "pointer",
          whiteSpace: "nowrap",
          transition: "background 0.15s",
          width: "100%",
          justifyContent: "space-between",
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", maxWidth: 160 }}>{display}</span>
        <span style={{ fontSize: 10, opacity: 0.6 }}>{open ? "â–²" : "â–¼"}</span>
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            right: 0,
            zIndex: 200,
            background: "#fff",
            border: "1px solid #E5E7EB",
            borderRadius: 10,
            boxShadow: "0 8px 24px rgba(0,0,0,0.10)",
            minWidth: 280,
            overflow: "hidden",
          }}
        >
          {/* Default option */}
          <button
            onClick={() => { onChange(null); setOpen(false); }}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              padding: "9px 14px",
              fontSize: 12,
              color: value === null ? "#002EFF" : "#111827",
              fontWeight: value === null ? 600 : 400,
              background: value === null ? "#EFF6FF" : "transparent",
              border: "none",
              cursor: "pointer",
              borderBottom: "1px solid #F3F4F6",
            }}
          >
            Default (system-assigned)
          </button>
          {availableModels.map((m) => (
            <button
              key={m}
              onClick={() => { onChange(m); setOpen(false); }}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "9px 14px",
                fontSize: 12,
                color: value === m ? "#002EFF" : "#111827",
                fontWeight: value === m ? 600 : 400,
                background: value === m ? "#EFF6FF" : "transparent",
                border: "none",
                cursor: "pointer",
                borderBottom: "1px solid #F3F4F6",
                lineHeight: 1.4,
              }}
            >
              <div style={{ fontWeight: 500 }}>{shortModelName(m)}</div>
              <div style={{ fontSize: 10, color: "#9CA3AF", marginTop: 1 }}>{m}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// â”€â”€ Main Panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

interface Props {
  founderId: string;
}

export default function ModelSettingsPanel({ founderId }: Props) {
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  // Staged local overrides (key -> model string, or null = cleared)
  const [staged, setStaged] = useState<Record<string, string | null>>({});
  // Last-saved overrides from server
  const [saved, setSaved] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Load current overrides on mount
  useEffect(() => {
    if (!founderId) return;
    setLoading(true);
    getModelSettings(founderId)
      .then((data) => {
        setSaved(data.overrides ?? {});
        setAvailableModels(data.available_models ?? []);
        setStaged({});
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [founderId]);

  // Effective value for a given agent (staged takes priority over saved)
  function effective(key: string): string | null {
    if (key in staged) return staged[key];
    return saved[key] ?? null;
  }

  function hasUnsavedChanges(): boolean {
    return Object.keys(staged).length > 0;
  }

  function handleChange(agentKey: string, model: string | null) {
    setStaged((prev) => {
      const next = { ...prev };
      // Only stage if different from saved
      const savedVal = saved[agentKey] ?? null;
      if (model === savedVal) {
        delete next[agentKey];
      } else {
        next[agentKey] = model;
      }
      return next;
    });
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const ops: Promise<unknown>[] = [];
      for (const [agentKey, model] of Object.entries(staged)) {
        if (model === null) {
          ops.push(clearModelOverride(founderId, agentKey));
        } else {
          ops.push(setModelOverride(founderId, agentKey, model));
        }
      }
      await Promise.all(ops);
      // Refresh from server
      const fresh = await getModelSettings(founderId);
      setSaved(fresh.overrides ?? {});
      setStaged({});
      setSuccessMsg(`Saved ${ops.length} model setting${ops.length === 1 ? "" : "s"}.`);
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  function handleResetAll() {
    setStaged({});
  }

  // Group agents by department
  const byDept = DEPARTMENT_ORDER.reduce<Record<Department, AgentMeta[]>>(
    (acc, dept) => {
      acc[dept] = AGENTS.filter((a) => a.department === dept);
      return acc;
    },
    {} as Record<Department, AgentMeta[]>
  );

  const overrideCount = Object.values(saved).filter(Boolean).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#111827", letterSpacing: "-0.01em" }}>
            AI Model Settings
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "#6B7280", lineHeight: 1.5 }}>
            Override which model each agent uses. Saved overrides apply on the next run.
            {overrideCount > 0 && (
              <span style={{ marginLeft: 8, color: "#002EFF", fontWeight: 500 }}>
                {overrideCount} override{overrideCount === 1 ? "" : "s"} active
              </span>
            )}
          </p>
        </div>

        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          {hasUnsavedChanges() && (
            <button
              onClick={handleResetAll}
              disabled={saving}
              style={{
                padding: "8px 16px",
                borderRadius: 8,
                border: "1px solid #E5E7EB",
                background: "#fff",
                color: "#6B7280",
                fontSize: 13,
                fontWeight: 500,
                cursor: "pointer",
              }}
            >
              Discard
            </button>
          )}
          <button
            onClick={handleSave}
            disabled={saving || !hasUnsavedChanges()}
            style={{
              padding: "8px 20px",
              borderRadius: 8,
              border: "none",
              background: hasUnsavedChanges() ? "#002EFF" : "#E5E7EB",
              color: hasUnsavedChanges() ? "#fff" : "#9CA3AF",
              fontSize: 13,
              fontWeight: 600,
              cursor: hasUnsavedChanges() ? "pointer" : "default",
              transition: "background 0.15s, color 0.15s",
            }}
          >
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>

      {/* Feedback */}
      {error && (
        <div style={{ padding: "10px 14px", borderRadius: 8, background: "#FEF2F2", border: "1px solid #FCA5A5", color: "#DC2626", fontSize: 13 }}>
          {error}
        </div>
      )}
      {successMsg && (
        <div style={{ padding: "10px 14px", borderRadius: 8, background: "#F0FDF4", border: "1px solid #86EFAC", color: "#16A34A", fontSize: 13 }}>
          {successMsg}
        </div>
      )}

      {/* Available Models Legend */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: "12px 16px", borderRadius: 10, background: "#F9FAFB", border: "1px solid #E5E7EB" }}>
        <span style={{ fontSize: 11, color: "#6B7280", alignSelf: "center", fontWeight: 500, marginRight: 4 }}>Available:</span>
        {availableModels.map((m) => (
          <span
            key={m}
            style={{
              fontSize: 11,
              padding: "3px 8px",
              borderRadius: 5,
              background: "#fff",
              border: "1px solid #E5E7EB",
              color: "#374151",
              fontFamily: "monospace",
            }}
          >
            {shortModelName(m)}
          </span>
        ))}
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: "40px 0", color: "#9CA3AF", fontSize: 14 }}>
          Loading model settings...
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {DEPARTMENT_ORDER.map((dept) => {
            const agents = byDept[dept];
            if (!agents || agents.length === 0) return null;
            const color = DEPT_COLOR[dept];
            const icon = DEPT_ICON[dept];
            const deptOverrides = agents.filter((a) => effective(a.key) !== null).length;

            return (
              <div
                key={dept}
                style={{
                  borderRadius: 14,
                  border: "1px solid #E5E7EB",
                  overflow: "hidden",
                  background: "#fff",
                }}
              >
                {/* Department header */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "11px 18px",
                    borderBottom: "1px solid #F3F4F6",
                    background: "#FAFAFA",
                  }}
                >
                  <span style={{ color, fontSize: 13, lineHeight: 1 }}>{icon}</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "#111827", letterSpacing: "0.04em", textTransform: "uppercase" }}>
                    {dept}
                  </span>
                  {deptOverrides > 0 && (
                    <span
                      style={{
                        marginLeft: "auto",
                        fontSize: 11,
                        padding: "2px 7px",
                        borderRadius: 999,
                        background: "#EFF6FF",
                        color: "#002EFF",
                        fontWeight: 600,
                      }}
                    >
                      {deptOverrides} overridden
                    </span>
                  )}
                </div>

                {/* Agent rows */}
                {agents.map((agent, idx) => {
                  const currentModel = effective(agent.key);
                  const isStaged = agent.key in staged;
                  const isOverridden = currentModel !== null;

                  return (
                    <div
                      key={agent.key}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 16,
                        padding: "12px 18px",
                        borderBottom: idx < agents.length - 1 ? "1px solid #F9FAFB" : "none",
                        background: isStaged ? "#FEFCE8" : "transparent",
                        transition: "background 0.15s",
                      }}
                    >
                      {/* Agent label */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ fontSize: 13, fontWeight: 500, color: "#111827" }}>
                            {agent.label}
                          </span>
                          {isStaged && (
                            <span style={{ fontSize: 10, color: "#92400E", background: "#FEF3C7", padding: "1px 6px", borderRadius: 4, fontWeight: 600 }}>
                              unsaved
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 2, fontFamily: "monospace" }}>
                          {agent.key}
                        </div>
                      </div>

                      {/* Current model badge (saved) */}
                      <div style={{ flexShrink: 0, minWidth: 100, textAlign: "right" }}>
                        {isOverridden ? (
                          <span style={{ fontSize: 11, color: "#002EFF", fontWeight: 600, background: "#EFF6FF", padding: "2px 8px", borderRadius: 5 }}>
                            {shortModelName(currentModel!)}
                          </span>
                        ) : (
                          <span style={{ fontSize: 11, color: "#9CA3AF" }}>Default</span>
                        )}
                      </div>

                      {/* Dropdown */}
                      <div style={{ flexShrink: 0 }}>
                        <ModelDropdown
                          value={currentModel}
                          availableModels={availableModels}
                          onChange={(m) => handleChange(agent.key, m)}
                        />
                      </div>

                      {/* Reset button â€” only shown if override is active */}
                      <div style={{ flexShrink: 0, width: 60, textAlign: "right" }}>
                        {(isOverridden) && (
                          <button
                            onClick={() => handleChange(agent.key, null)}
                            style={{
                              padding: "4px 10px",
                              borderRadius: 6,
                              border: "1px solid #E5E7EB",
                              background: "#fff",
                              color: "#6B7280",
                              fontSize: 11,
                              cursor: "pointer",
                              whiteSpace: "nowrap",
                            }}
                          >
                            Reset
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}

      {/* Bottom save bar â€” sticky when there are changes */}
      {hasUnsavedChanges() && (
        <div
          style={{
            position: "sticky",
            bottom: 16,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 20px",
            borderRadius: 12,
            background: "#111827",
            color: "#fff",
            boxShadow: "0 8px 24px rgba(0,0,0,0.20)",
          }}
        >
          <span style={{ fontSize: 13 }}>
            <strong>{Object.keys(staged).length}</strong> unsaved change{Object.keys(staged).length === 1 ? "" : "s"}
          </span>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={handleResetAll}
              style={{ padding: "7px 14px", borderRadius: 8, border: "1px solid #374151", background: "transparent", color: "#D1D5DB", fontSize: 13, cursor: "pointer" }}
            >
              Discard
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              style={{ padding: "7px 18px", borderRadius: 8, border: "none", background: "#002EFF", color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
            >
              {saving ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

