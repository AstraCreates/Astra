"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { apiFetch } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const MAX_CONFIRM = 10;

// ── Types ──────────────────────────────────────────────────────────────────────

interface TargetAudience {
  titles: string;
  locations: string;
  industries: string;
  keywords: string;
  seniorities: string[];
  company_sizes: string[];
}

interface ApolloContact {
  apollo_id: string;
  first_name: string;
  last_name: string;
  title: string;
  company_name: string;
  has_email: boolean;
  has_phone: boolean;
  city?: string;
  country?: string;
  email?: string;
  enriched?: boolean;
  company_industry?: string;
  company_size?: string;
  company_website?: string;
  company_description?: string;
  company_funding?: string;
  is_org?: boolean;
}

interface EnrolledContact {
  id: string;
  contact_id: string;
  status: string;
  current_step: number;
  last_sent_at?: string;
  next_send_at?: string;
  outreach_contacts?: {
    first_name: string;
    last_name: string;
    email: string;
    company_name: string;
    title: string;
  };
}

interface CampaignStep {
  subject: string;
  body: string;
  send_day: number;
  type?: string;
}

interface Campaign {
  id: string;
  name: string;
  status: string;
  from_name: string;
  from_email: string;
  product_name: string;
  value_prop: string;
  steps: CampaignStep[];
  daily_limit: number;
  send_provider: string;
  target_audience?: TargetAudience;
  created_at: string;
}

interface CampaignStats {
  sent: number;
  opened: number;
  clicked: number;
  replied: number;
  open_rate: number;
  click_rate: number;
  reply_rate: number;
}

// ── Design helpers ─────────────────────────────────────────────────────────────

function card(extra?: React.CSSProperties): React.CSSProperties {
  return { background: "var(--surface)", border: "1px solid var(--bd2)", ...extra };
}

function section(extra?: React.CSSProperties): React.CSSProperties {
  return { background: "var(--s2)", border: "1px solid var(--bd)", ...extra };
}

// Status pill helper — returns className for <span className={statusPill(s)} />
function statusPillClass(status: string): string {
  const map: Record<string, string> = {
    active: "pill green", paused: "pill amber",
    completed: "pill blue", active_contacted: "pill blue",
  };
  return map[status] ?? "pill";
}

// ── Filter options ─────────────────────────────────────────────────────────────

const SENIORITY_OPTIONS = [
  { value: "c_suite", label: "C-Suite" },
  { value: "vp", label: "VP" },
  { value: "director", label: "Director" },
  { value: "manager", label: "Manager" },
  { value: "senior", label: "Senior" },
  { value: "entry", label: "Entry" },
];

const COMPANY_SIZE_OPTIONS = [
  { value: "1,10", label: "1–10" },
  { value: "11,50", label: "11–50" },
  { value: "51,200", label: "51–200" },
  { value: "201,500", label: "201–500" },
  { value: "501,1000", label: "501–1K" },
  { value: "1001,5000", label: "1K–5K" },
  { value: "5001,10000", label: "5K+" },
];

// ── Sub-components ─────────────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="f-label">{label}</label>
      {children}
    </div>
  );
}

function CheckGroup({ label, options, selected, onChange }: {
  label: string; options: { value: string; label: string }[];
  selected: string[]; onChange: (v: string[]) => void;
}) {
  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter(x => x !== v) : [...selected, v]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <span className="f-label">{label}</span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {options.map(o => (
          <button key={o.value} onClick={() => toggle(o.value)} style={{
            padding: "3px 10px", fontSize: 11, fontFamily: "var(--font-ibm-mono), monospace",
            background: selected.includes(o.value) ? "var(--bdim)" : "transparent",
            border: `1px solid ${selected.includes(o.value) ? "var(--bb)" : "var(--bd2)"}`,
            color: selected.includes(o.value) ? "var(--blue)" : "var(--fm)",
            cursor: "pointer", transition: "all 0.12s",
          }}>{o.label}</button>
        ))}
      </div>
    </div>
  );
}

const SEARCH_STAGES = [
  "Connecting to contact database…",
  "Applying your filters…",
  "Fetching matching contacts…",
  "Loading company details…",
  "Ranking by relevance…",
];

function ProgressBar({ label, stages }: { label: string; stages?: string[] }) {
  const stageList = stages || [label];
  const [stageIdx, setStageIdx] = React.useState(0);

  React.useEffect(() => {
    setStageIdx(0);
    if (stageList.length <= 1) return;
    const interval = setInterval(() => {
      setStageIdx(i => Math.min(i + 1, stageList.length - 1));
    }, 2200);
    return () => clearInterval(interval);
  }, [label]); // reset when a new search starts

  const current = stageList[stageIdx];
  const pct = stageList.length > 1 ? Math.round(((stageIdx + 1) / stageList.length) * 100) : null;

  return (
    <div style={{ padding: "28px 24px", textAlign: "center" }}>
      <div style={{ fontSize: 13, color: "var(--fm)", marginBottom: 14 }}>{current}</div>
      <div style={{ height: 2, background: "var(--bd)", overflow: "hidden", maxWidth: 320, margin: "0 auto" }}>
        {pct !== null ? (
          <div style={{
            height: "100%", background: "var(--blue)",
            width: `${pct}%`, transition: "width 1.8s ease",
          }} />
        ) : (
          <div style={{
            height: "100%",
            background: "linear-gradient(90deg, transparent 0%, var(--blue) 40%, var(--mint) 70%, transparent 100%)",
            backgroundSize: "200% 100%",
            animation: "outreach-sweep 1.8s ease-in-out infinite",
          }} />
        )}
      </div>
      {pct !== null && (
        <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 8, fontFamily: "var(--font-ibm-mono), monospace" }}>
          Step {stageIdx + 1} of {stageList.length}
        </div>
      )}
    </div>
  );
}

function StatBadge({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div style={{ textAlign: "center", padding: "8px 14px", ...section() }}>
      <div style={{ fontSize: 17, fontWeight: 700, color: color || "var(--fg)", fontFamily: "var(--font-ibm-mono), monospace" }}>{value}</div>
      <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--fm)", marginTop: 2 }}>{label}</div>
    </div>
  );
}

// ── Campaign card ──────────────────────────────────────────────────────────────

function CampaignCard({ campaign, stats, onClick, onDelete }: {
  campaign: Campaign; stats?: CampaignStats; onClick: () => void; onDelete: () => void;
}) {
  const [confirming, setConfirming] = React.useState(false);
  const audience = campaign.target_audience;
  const hasAudience = audience && (audience.titles || audience.industries || audience.locations);
  return (
    <div className="sc" style={{ cursor: "default", padding: 0 }}>
      {/* Clickable body — delete button is never inside this */}
      <div onClick={onClick} style={{ cursor: "pointer", padding: "14px 14px 10px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)" }}>{campaign.name}</div>
            <div style={{ fontSize: 11, color: "var(--fm)", marginTop: 2 }}>{campaign.from_email || "no sender"}</div>
          </div>
          <span className={statusPillClass(campaign.status)} style={{ flexShrink: 0, marginLeft: 8 }}>{campaign.status}</span>
        </div>
        {hasAudience && (
          <div style={{ fontSize: 11, color: "var(--fm)", marginBottom: 8 }}>
            {[audience!.titles, audience!.industries, audience!.locations].filter(Boolean).join(" · ")}
          </div>
        )}
        {stats && stats.sent > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginBottom: 8 }}>
            <StatBadge label="Sent" value={stats.sent} />
            <StatBadge label="Opens" value={`${stats.open_rate}%`} color="var(--blue)" />
            <StatBadge label="Replies" value={`${stats.reply_rate}%`} color="var(--green)" />
          </div>
        )}
        <div style={{ fontSize: 10, color: "var(--fm)", fontFamily: "var(--font-ibm-mono), monospace" }}>
          {campaign.steps?.length || 0} email steps · {campaign.daily_limit}/day
        </div>
      </div>
      {/* Delete row — outside the clickable body */}
      <div style={{ borderTop: "1px solid var(--bd)", padding: "6px 10px", display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 6 }}>
        {confirming ? (
          <>
            <span style={{ fontSize: 11, color: "var(--fg)" }}>Delete this campaign?</span>
            <button onClick={() => { setConfirming(false); onDelete(); }} style={{ background: "var(--rdim)", border: "1px solid var(--rb)", color: "var(--red)", cursor: "pointer", fontSize: 11, fontWeight: 600, padding: "2px 10px" }}>
              Yes
            </button>
            <button onClick={() => setConfirming(false)} style={{ background: "none", border: "1px solid var(--bd2)", color: "var(--fm)", cursor: "pointer", fontSize: 11, padding: "2px 10px" }}>
              Cancel
            </button>
          </>
        ) : (
          <button onClick={() => setConfirming(true)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "var(--red)", fontWeight: 600, padding: "2px 6px" }}>
            Delete
          </button>
        )}
      </div>
    </div>
  );
}

// ── Apollo contact card ────────────────────────────────────────────────────────

function ContactCard({ contact, selected, onToggle, disabled }: {
  contact: ApolloContact; selected: boolean; onToggle: () => void; disabled: boolean;
}) {
  const companyMeta = [contact.company_industry, contact.company_size, contact.company_funding]
    .filter(Boolean).join(" · ");
  return (
    <div
      onClick={disabled && !selected ? undefined : onToggle}
      style={{
        padding: "12px 14px", cursor: disabled && !selected ? "not-allowed" : "pointer",
        background: selected ? "var(--bdim)" : "var(--surface)",
        border: `1px solid ${selected ? "var(--bb)" : "var(--bd)"}`,
        transition: "all 0.1s", opacity: disabled && !selected ? 0.45 : 1,
        display: "flex", gap: 11, alignItems: "flex-start",
      }}
      onMouseEnter={e => { if (!disabled || selected) (e.currentTarget as HTMLElement).style.borderColor = "var(--bb)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = selected ? "var(--bb)" : "var(--bd)"; }}
    >
      <div style={{
        width: 15, height: 15, flexShrink: 0, marginTop: 2,
        border: `1.5px solid ${selected ? "var(--blue)" : "var(--bd2)"}`,
        background: selected ? "var(--blue)" : "transparent",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        {selected && <span style={{ fontSize: 9, color: "#fff", fontWeight: 700 }}>✓</span>}
      </div>
      <div style={{ minWidth: 0, flex: 1, display: "flex", flexDirection: "column", gap: 3 }}>
        {contact.is_org ? (
          /* ── Org card ── */
          <>
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--fg)", display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ fontSize: 10, opacity: 0.5 }}>🏢</span> {contact.first_name}
            </div>
            {companyMeta && <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 1 }}>{companyMeta}</div>}
            {contact.company_description && (
              <div style={{ fontSize: 10, color: "var(--fd)", marginTop: 3, lineHeight: 1.45 }}>
                {contact.company_description}
              </div>
            )}
            {contact.company_website && (
              <div style={{ fontSize: 10, color: "var(--blue)", marginTop: 2, fontFamily: "var(--font-ibm-mono), monospace" }}>
                {contact.company_website.replace(/^https?:\/\//, "")}
              </div>
            )}
          </>
        ) : (
          /* ── Person card ── */
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>
                {contact.first_name} {contact.last_name}
              </span>
              {contact.email && (
                <span className="pill blue" style={{ fontSize: 9, padding: "1px 6px" }}>✓ email revealed</span>
              )}
            </div>
            <div style={{ fontSize: 11, color: "var(--fm)" }}>{contact.title}</div>
            <div style={{ marginTop: 4, paddingTop: 6, borderTop: "1px solid var(--bd)" }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)" }}>{contact.company_name}</div>
              {companyMeta && <div style={{ fontSize: 10, color: "var(--fm)", marginTop: 2 }}>{companyMeta}</div>}
              {contact.company_description && (
                <div style={{ fontSize: 10, color: "var(--fd)", marginTop: 3, lineHeight: 1.45 }}>
                  {contact.company_description}
                </div>
              )}
              {contact.company_website && (
                <div style={{ fontSize: 10, color: "var(--blue)", marginTop: 2, fontFamily: "var(--font-ibm-mono), monospace" }}>
                  {contact.company_website.replace(/^https?:\/\//, "")}
                </div>
              )}
            </div>
            {contact.email && (
              <div style={{ fontSize: 10, color: "var(--blue)", fontFamily: "var(--font-ibm-mono), monospace" }}>
                {contact.email}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Inline button helpers ──────────────────────────────────────────────────────

const Btn = ({ children, onClick, disabled, variant = "ghost", style: s }: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "ghost" | "blue" | "green" | "amber" | "danger";
  style?: React.CSSProperties;
}) => {
  const variantStyles: Record<string, React.CSSProperties> = {
    ghost: { background: "transparent", border: "1px solid var(--bd2)", color: "var(--fd)" },
    blue:  { background: "var(--bdim)", border: "1px solid var(--bb)", color: "var(--blue)" },
    green: { background: "var(--gdim)", border: "1px solid var(--gb)", color: "var(--green)" },
    amber: { background: "var(--adim)", border: "1px solid var(--ab)", color: "var(--amber)" },
    danger:{ background: "var(--rdim)", border: "1px solid var(--rb)", color: "var(--red)" },
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: "0 18px", height: 36, fontSize: 12, fontWeight: 600,
        fontFamily: "var(--font-dm-sans), sans-serif",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1, transition: "all .12s", whiteSpace: "nowrap",
        letterSpacing: "0.03em",
        ...variantStyles[variant],
        ...s,
      }}
    >
      {children}
    </button>
  );
};

// ── Main component ─────────────────────────────────────────────────────────────

type View = "campaigns" | "detail";
type DetailTab = "find" | "enrolled" | "emails";

export default function OutreachPage() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;

  const [view, setView] = useState<View>("campaigns");
  const [activeCampaign, setActiveCampaign] = useState<Campaign | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("find");

  // ── Campaigns list ─────────────────────────────────────────────────────────
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [campaignStats, setCampaignStats] = useState<Record<string, CampaignStats>>({});
  const [campaignsLoading, setCampaignsLoading] = useState(false);
  const [showNewCampaign, setShowNewCampaign] = useState(false);

  const defaultAudience = (): TargetAudience => ({
    titles: "", locations: "", industries: "", keywords: "", seniorities: [], company_sizes: [],
  });

  const [newCampaign, setNewCampaign] = useState({
    name: "", from_name: "", from_email: "", product_name: "", value_prop: "", daily_limit: 50,
  });
  const [newAudience, setNewAudience] = useState<TargetAudience>(defaultAudience());
  const [audienceMode, setAudienceMode] = useState<"simple" | "advanced">("simple");
  const [audiencePrompt, setAudiencePrompt] = useState("");
  const [parsingAudience, setParsingAudience] = useState(false);
  const [creatingCampaign, setCreatingCampaign] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // ── Find contacts tab ──────────────────────────────────────────────────────
  const [apolloResults, setApolloResults] = useState<ApolloContact[]>([]);
  const [apolloTotal, setApolloTotal] = useState(0);
  const [apolloSearching, setApolloSearching] = useState(false);
  const [apolloError, setApolloError] = useState("");
  const [selectedContacts, setSelectedContacts] = useState<Set<string>>(new Set());
  const [enrolling, setEnrolling] = useState(false);
  const [enrollResult, setEnrollResult] = useState<{ enrolled: number; credits_used: number } | null>(null);
  const [findAudience, setFindAudience] = useState<TargetAudience>(defaultAudience());
  const [apolloSource, setApolloSource] = useState("");
  const [showRefine, setShowRefine] = useState(false);
  const apolloFetchedForRef = useRef<string>("");

  // ── Enrolled tab ───────────────────────────────────────────────────────────
  const [enrolled, setEnrolled] = useState<EnrolledContact[]>([]);
  const [enrolledLoading, setEnrolledLoading] = useState(false);

  // ── Emails tab ─────────────────────────────────────────────────────────────
  const [editingSteps, setEditingSteps] = useState<CampaignStep[]>([]);
  const [savingSteps, setSavingSteps] = useState(false);
  const [generatingSteps, setGeneratingSteps] = useState(false);
  const [sendingBatch, setSendingBatch] = useState(false);
  const [batchResult, setBatchResult] = useState<{ sent: number; failed: number } | null>(null);

  // ── Load campaigns ─────────────────────────────────────────────────────────

  const loadCampaigns = useCallback(async () => {
    setCampaignsLoading(true);
    try {
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}`);
      const data = await res.json();
      const camps: Campaign[] = data.campaigns || [];
      setCampaigns(camps);
      const statsEntries = await Promise.all(
        camps.map(async c => {
          try {
            const sr = await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${c.id}/stats`);
            return [c.id, await sr.json()] as [string, CampaignStats];
          } catch { return [c.id, null] as [string, null]; }
        })
      );
      const statsMap: Record<string, CampaignStats> = {};
      for (const [id, s] of statsEntries) { if (s) statsMap[id] = s; }
      setCampaignStats(statsMap);
    } catch { /* ignore */ }
    finally { setCampaignsLoading(false); }
  }, [founderId]);

  useEffect(() => { loadCampaigns(); }, [loadCampaigns]);

  // ── Enter campaign detail ──────────────────────────────────────────────────

  const enterCampaign = (c: Campaign) => {
    setActiveCampaign(c);
    setView("detail");
    setDetailTab("find");
    setSelectedContacts(new Set());
    setEnrollResult(null);
    setBatchResult(null);
    setApolloResults([]);
    setApolloError("");
    setApolloSource("");
    apolloFetchedForRef.current = "";
    setFindAudience(c.target_audience ?? defaultAudience());
    setEditingSteps(c.steps ? JSON.parse(JSON.stringify(c.steps)) : []);
  };

  // ── Apollo search ──────────────────────────────────────────────────────────

  const runApolloSearch = useCallback(async (audience: TargetAudience) => {
    setApolloSearching(true);
    setApolloError("");
    setSelectedContacts(new Set());
    try {
      const params = new URLSearchParams({ founder_id: founderId, page: "1", per_page: "100" });
      if (audience.titles) params.set("titles", audience.titles);
      if (audience.locations) params.set("locations", audience.locations);
      if (audience.industries) params.set("industries", audience.industries);
      if (audience.keywords) params.set("keywords", audience.keywords);
      if (audience.seniorities.length) params.set("seniorities", audience.seniorities.join(","));
      if (audience.company_sizes.length) params.set("company_sizes", audience.company_sizes.join(","));
      const res = await apiFetch(`${BASE}/outreach/search/people?${params}`);
      const data = await res.json();
      if (data.error) { setApolloError(JSON.stringify(data.error)); return; }
      // Ensure every contact has a unique stable ID regardless of source
      const contacts = (data.contacts || []).map((c: ApolloContact, idx: number) => ({
        ...c,
        apollo_id: c.apollo_id || `_local_${idx}_${(c.first_name || "").replace(/\s/g, "")}_${(c.company_name || "").replace(/\s/g, "")}`,
      }));
      setApolloResults(contacts);
      setApolloTotal(data.total || 0);
      setApolloSource(data.source || "");
    } catch (e) {
      setApolloError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setApolloSearching(false);
    }
  }, [founderId]);

  useEffect(() => {
    if (view !== "detail" || detailTab !== "find" || !activeCampaign) return;
    const cacheKey = `${activeCampaign.id}-${JSON.stringify(findAudience)}`;
    if (apolloFetchedForRef.current === cacheKey) return;
    apolloFetchedForRef.current = cacheKey;
    runApolloSearch(findAudience);
  }, [view, detailTab, activeCampaign, findAudience, runApolloSearch]);

  // ── Load enrolled contacts ─────────────────────────────────────────────────

  const loadEnrolled = useCallback(async () => {
    if (!activeCampaign) return;
    setEnrolledLoading(true);
    try {
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${activeCampaign.id}/contacts`);
      const data = await res.json();
      setEnrolled(data.contacts || []);
    } catch { /* ignore */ }
    finally { setEnrolledLoading(false); }
  }, [founderId, activeCampaign]);

  useEffect(() => {
    if (view === "detail" && detailTab === "enrolled") loadEnrolled();
  }, [view, detailTab, loadEnrolled]);

  // ── Confirm contacts ───────────────────────────────────────────────────────

  const confirmContacts = async () => {
    if (!activeCampaign || selectedContacts.size === 0) return;
    setEnrolling(true);
    setEnrollResult(null);
    try {
      const toEnrich = apolloResults
        .filter(c => selectedContacts.has(c.apollo_id))
        .slice(0, MAX_CONFIRM)
        .map(c => ({ ...c, apollo_id: c.apollo_id.startsWith("_local_") ? "" : c.apollo_id }));
      const enrichRes = await apiFetch(`${BASE}/outreach/enrich/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: founderId, contacts: toEnrich }),
      });
      const enrichData = await enrichRes.json();
      const enriched: ApolloContact[] = enrichData.enriched || [];
      const creditsUsed: number = enrichData.credits_used || 0;

      const saveRes = await apiFetch(`${BASE}/outreach/contacts/${founderId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contacts: enriched }),
      });
      const saveData = await saveRes.json();
      const contactIds = (saveData.contacts || []).map((c: { id: string }) => c.id).filter(Boolean);

      if (contactIds.length > 0) {
        await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${activeCampaign.id}/contacts`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ contact_ids: contactIds }),
        });
      }

      setEnrollResult({ enrolled: contactIds.length, credits_used: creditsUsed });
      setSelectedContacts(new Set());
      setApolloResults(prev => prev.map(c => {
        const match = enriched.find(e => e.apollo_id === c.apollo_id);
        return match ? { ...c, ...match } : c;
      }));
      setDetailTab("enrolled");
    } catch (e) {
      setApolloError(e instanceof Error ? e.message : "Confirm failed");
    } finally {
      setEnrolling(false);
    }
  };

  // ── Campaign CRUD ──────────────────────────────────────────────────────────

  const createCampaign = async () => {
    setCreatingCampaign(true);
    try {
      let audience: TargetAudience;
      if (audienceMode === "simple" && audiencePrompt.trim()) {
        setParsingAudience(true);
        try {
          const parseRes = await apiFetch(`${BASE}/outreach/parse-audience`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt: audiencePrompt.trim() }),
          });
          const parsed = await parseRes.json();
          audience = parsed.error
            ? { ...defaultAudience(), keywords: audiencePrompt.trim() }
            : {
                titles: parsed.titles || "",
                locations: parsed.locations || "",
                industries: parsed.industries || "",
                keywords: parsed.keywords || "",
                seniorities: parsed.seniorities || [],
                company_sizes: parsed.company_sizes || [],
              };
        } catch {
          audience = { ...defaultAudience(), keywords: audiencePrompt.trim() };
        } finally {
          setParsingAudience(false);
        }
      } else {
        audience = audienceMode === "simple"
          ? defaultAudience()
          : newAudience;
      }
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...newCampaign, target_audience: audience }),
      });
      const data = await res.json();
      setShowNewCampaign(false);
      setNewCampaign({ name: "", from_name: "", from_email: "", product_name: "", value_prop: "", daily_limit: 50 });
      setNewAudience(defaultAudience());
      setAudienceMode("simple");
      setAudiencePrompt("");
      setParsingAudience(false);
      await loadCampaigns();
      enterCampaign(data);
    } catch (e) {
      alert("Failed: " + (e instanceof Error ? e.message : e));
    } finally {
      setCreatingCampaign(false);
    }
  };

  // ── Email sequence ─────────────────────────────────────────────────────────

  const generateSteps = async () => {
    if (!activeCampaign) return;
    setGeneratingSteps(true);
    try {
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${activeCampaign.id}/generate-steps`, { method: "POST" });
      const data = await res.json();
      setEditingSteps(data.steps ? JSON.parse(JSON.stringify(data.steps)) : []);
      setActiveCampaign(prev => prev ? { ...prev, steps: data.steps } : prev);
    } catch { /* ignore */ }
    finally { setGeneratingSteps(false); }
  };

  const saveSteps = async () => {
    if (!activeCampaign) return;
    setSavingSteps(true);
    try {
      await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${activeCampaign.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ steps: editingSteps }),
      });
      setActiveCampaign(prev => prev ? { ...prev, steps: editingSteps } : prev);
    } catch (e) { alert("Save failed: " + (e instanceof Error ? e.message : e)); }
    finally { setSavingSteps(false); }
  };

  const sendBatch = async () => {
    if (!activeCampaign) return;
    setSendingBatch(true);
    setBatchResult(null);
    try {
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${activeCampaign.id}/send-batch`, { method: "POST" });
      const data = await res.json();
      setBatchResult({ sent: data.sent, failed: data.failed });
    } catch (e) { alert("Send failed: " + (e instanceof Error ? e.message : e)); }
    finally { setSendingBatch(false); }
  };

  const deleteCampaign = async (campaignId: string, campaignName: string) => {
    try {
      await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${campaignId}`, { method: "DELETE" });
      if (activeCampaign?.id === campaignId) {
        setView("campaigns");
        setActiveCampaign(null);
      }
      await loadCampaigns();
    } catch (e) { alert("Delete failed: " + (e instanceof Error ? e.message : e)); }
  };

  const updateCampaignStatus = async (status: string) => {
    if (!activeCampaign) return;
    await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${activeCampaign.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    setActiveCampaign(prev => prev ? { ...prev, status } : prev);
    await loadCampaigns();
  };

  const toggleContact = (apolloId: string) => {
    setSelectedContacts(prev => {
      const next = new Set(prev);
      if (next.has(apolloId)) { next.delete(apolloId); }
      else if (next.size < MAX_CONFIRM) { next.add(apolloId); }
      return next;
    });
  };

  const stats = activeCampaign ? campaignStats[activeCampaign.id] : null;

  // ══════════════════════════════════════════════════════════════════════════
  // RENDER
  // ══════════════════════════════════════════════════════════════════════════

  // ── Campaign list ──────────────────────────────────────────────────────────

  if (view === "campaigns") return (
    <div style={{ width: "100%", maxWidth: 1100, margin: "0 auto", display: "flex", flexDirection: "column", gap: 20 }}>
      <style>{`@keyframes outreach-sweep{0%{background-position:200% 0}100%{background-position:-200% 0}}`}</style>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: "var(--fg)" }}>Outreach</h1>
          <p style={{ fontSize: 13, color: "var(--fm)", margin: "4px 0 0" }}>
            Create a campaign, find contacts, and send personalised emails
          </p>
        </div>
        <button onClick={() => setShowNewCampaign(true)} className="btn pri">
          + New Campaign
        </button>
      </div>

      {campaignsLoading ? (
        <div style={{ ...section() }}>
          <ProgressBar label="Loading campaigns…" />
        </div>
      ) : campaigns.length === 0 ? (
        <div style={{ ...card({ padding: "60px 24px", textAlign: "center" }) }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📨</div>
          <p style={{ fontSize: 15, fontWeight: 600, color: "var(--fg)", margin: "0 0 6px" }}>No campaigns yet</p>
          <p style={{ fontSize: 13, color: "var(--fm)", margin: "0 0 20px" }}>
            Create one to start finding contacts and sending emails
          </p>
          <button onClick={() => setShowNewCampaign(true)} className="btn pri">
            Create first campaign
          </button>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 10 }}>
          {campaigns.map(c => (
            <CampaignCard key={c.id} campaign={c} stats={campaignStats[c.id]} onClick={() => enterCampaign(c)} onDelete={() => deleteCampaign(c.id, c.name)} />
          ))}
        </div>
      )}

      {/* ── New campaign modal ──────────────────────────────────────────────── */}
      {showNewCampaign && (
        <div style={{ position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24, overflowY: "auto" }}>
          <div style={{ ...card({ padding: "28px 24px", width: "100%", maxWidth: 560 }), maxHeight: "90vh", overflowY: "auto", boxShadow: "0 24px 60px rgba(0,0,0,.14)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 22 }}>
              <h2 style={{ fontSize: 17, margin: 0, color: "var(--fg)" }}>New Campaign</h2>
              <button onClick={() => { setShowNewCampaign(false); setAudienceMode("simple"); setAudiencePrompt(""); setParsingAudience(false); }} style={{ background: "none", border: "none", color: "var(--fm)", cursor: "pointer", fontSize: 18, lineHeight: 1 }}>✕</button>
            </div>

            <div className="sec-label" style={{ marginBottom: 10 }}>Campaign basics</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 22 }}>
              {[
                { label: "Campaign Name *", key: "name", placeholder: "Q1 SaaS Outreach" },
                { label: "From Name", key: "from_name", placeholder: "Alex from Astra" },
                { label: "From Email", key: "from_email", placeholder: "alex@yourcompany.com" },
                { label: "Product Name", key: "product_name", placeholder: "Astra" },
                { label: "Value Proposition", key: "value_prop", placeholder: "Helps founders build startups 10x faster" },
              ].map(f => (
                <Field key={f.key} label={f.label}>
                  <input
                    value={(newCampaign as Record<string, string | number>)[f.key] as string}
                    onChange={e => setNewCampaign(p => ({ ...p, [f.key]: e.target.value }))}
                    placeholder={f.placeholder}
                    className="f-input"
                  />
                </Field>
              ))}
            </div>

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
              <span className="sec-label" style={{ margin: 0 }}>Target audience</span>
              <button
                type="button"
                onClick={() => setAudienceMode(m => m === "simple" ? "advanced" : "simple")}
                style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 11, color: "var(--blue)", fontWeight: 600 }}
              >
                {audienceMode === "simple" ? "Advanced filters ▼" : "Simple mode ▲"}
              </button>
            </div>

            {audienceMode === "simple" ? (
              <div style={{ marginBottom: 22 }}>
                <Field label="Describe who you want to reach">
                  <input
                    value={audiencePrompt}
                    onChange={e => setAudiencePrompt(e.target.value)}
                    placeholder="e.g. restaurant owners in New York, SaaS founders in the US"
                    className="f-input"
                  />
                </Field>
                <p style={{ fontSize: 11, color: "var(--fm)", margin: "6px 0 0" }}>
                  AI will convert this to search filters. Switch to manual for exact control.
                </p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 22 }}>
                {[
                  { label: "Job Titles", key: "titles", placeholder: "Owner, Manager, Chef, Director" },
                  { label: "Locations", key: "locations", placeholder: "New York, United States, California" },
                  { label: "Industries", key: "industries", placeholder: "Restaurants, Food & Beverages, Retail" },
                  { label: "Keywords", key: "keywords", placeholder: "catering, franchise, fine dining" },
                ].map(f => (
                  <Field key={f.key} label={f.label}>
                    <input
                      value={(newAudience as unknown as Record<string, string>)[f.key] ?? ""}
                      onChange={e => setNewAudience(a => ({ ...a, [f.key]: e.target.value }))}
                      placeholder={f.placeholder}
                      className="f-input"
                    />
                  </Field>
                ))}
                <CheckGroup label="Seniority" options={SENIORITY_OPTIONS} selected={newAudience.seniorities} onChange={v => setNewAudience(a => ({ ...a, seniorities: v }))} />
                <CheckGroup label="Company Size" options={COMPANY_SIZE_OPTIONS} selected={newAudience.company_sizes} onChange={v => setNewAudience(a => ({ ...a, company_sizes: v }))} />
              </div>
            )}

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", paddingTop: 8, borderTop: "1px solid var(--bd)" }}>
              <button onClick={() => { setShowNewCampaign(false); setAudienceMode("simple"); setAudiencePrompt(""); setParsingAudience(false); }} className="btn">Cancel</button>
              <button onClick={createCampaign} disabled={creatingCampaign || !newCampaign.name.trim()} className="btn pri">
                {parsingAudience ? "Parsing audience…" : creatingCampaign ? "Creating…" : "Create & Find Contacts →"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  // ── Campaign detail ────────────────────────────────────────────────────────

  if (!activeCampaign) return null;

  const DETAIL_TABS: { key: DetailTab; label: string }[] = [
    { key: "find", label: "Find Contacts" },
    { key: "enrolled", label: "Enrolled" },
    { key: "emails", label: "Emails" },
  ];

  return (
    <div style={{ width: "100%", maxWidth: 1100, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
      <style>{`@keyframes outreach-sweep{0%{background-position:200% 0}100%{background-position:-200% 0}}`}</style>

      {/* Detail header */}
      <div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <button
            onClick={() => { setView("campaigns"); setActiveCampaign(null); setConfirmingDelete(false); loadCampaigns(); }}
            style={{ background: "none", border: "none", color: "var(--fm)", cursor: "pointer", fontSize: 12, padding: 0, fontFamily: "var(--font-ibm-mono), monospace" }}
          >
            ← All campaigns
          </button>
          {confirmingDelete ? (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 12, color: "var(--fg)" }}>Delete this campaign?</span>
              <Btn variant="danger" onClick={() => { setConfirmingDelete(false); deleteCampaign(activeCampaign.id, activeCampaign.name); }}>Yes, delete</Btn>
              <Btn variant="ghost" onClick={() => setConfirmingDelete(false)}>Cancel</Btn>
            </div>
          ) : (
            <Btn variant="danger" onClick={() => setConfirmingDelete(true)}>Delete campaign</Btn>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, color: "var(--fg)" }}>{activeCampaign.name}</h1>
              <span className={statusPillClass(activeCampaign.status)}>{activeCampaign.status}</span>
            </div>
            <div style={{ fontSize: 12, color: "var(--fm)", marginTop: 4 }}>
              {activeCampaign.from_name} · {activeCampaign.from_email || "no sender set"} · {activeCampaign.daily_limit}/day
            </div>
          </div>
          {stats && stats.sent > 0 && (
            <div style={{ display: "flex", gap: 8 }}>
              <StatBadge label="Sent" value={stats.sent} />
              <StatBadge label="Opens" value={`${stats.open_rate}%`} color="var(--blue)" />
              <StatBadge label="Replies" value={`${stats.reply_rate}%`} color="var(--green)" />
            </div>
          )}
        </div>

        {/* Tab bar */}
        <div className="dtabs" style={{ marginTop: 14, borderBottom: "none", padding: 0, gap: 2 }}>
          {DETAIL_TABS.map(t => (
            <button key={t.key} className={`dtab${detailTab === t.key ? " on" : ""}`} onClick={() => setDetailTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
        <div style={{ height: 1, background: "var(--bd)" }} />
      </div>

      {/* ── Find Contacts tab ─────────────────────────────────────────────── */}
      {detailTab === "find" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

          {/* Audience strip */}
          <div style={{ ...card({ padding: "12px 16px" }), display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div style={{ fontSize: 13, color: "var(--fd)" }}>
              {[findAudience.titles, findAudience.industries, findAudience.locations, findAudience.keywords]
                .filter(Boolean).join(" · ") || <span style={{ color: "var(--fm)" }}>No filters set — showing broad results</span>}
            </div>
            <button onClick={() => setShowRefine(r => !r)} className="btn" style={{ flexShrink: 0, fontSize: 11 }}>
              {showRefine ? "Hide filters" : "Refine search"}
            </button>
          </div>

          {/* Refine panel */}
          {showRefine && (
            <div style={{ ...section({ padding: "16px 18px" }), display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                {[
                  { label: "Job Titles", key: "titles", placeholder: "CEO, CTO, Founder" },
                  { label: "Locations", key: "locations", placeholder: "United States" },
                  { label: "Industries", key: "industries", placeholder: "SaaS, Fintech" },
                  { label: "Keywords", key: "keywords", placeholder: "startup, growth" },
                ].map(f => (
                  <Field key={f.key} label={f.label}>
                    <input
                      value={(findAudience as unknown as Record<string, string>)[f.key] ?? ""}
                      onChange={e => setFindAudience(a => ({ ...a, [f.key]: e.target.value }))}
                      placeholder={f.placeholder}
                      className="f-input"
                    />
                  </Field>
                ))}
              </div>
              <CheckGroup label="Seniority" options={SENIORITY_OPTIONS} selected={findAudience.seniorities} onChange={v => setFindAudience(a => ({ ...a, seniorities: v }))} />
              <CheckGroup label="Company Size" options={COMPANY_SIZE_OPTIONS} selected={findAudience.company_sizes} onChange={v => setFindAudience(a => ({ ...a, company_sizes: v }))} />
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <Btn variant="blue" disabled={apolloSearching} onClick={() => { apolloFetchedForRef.current = ""; runApolloSearch(findAudience); setShowRefine(false); }}>
                  {apolloSearching ? "Searching…" : "Search →"}
                </Btn>
              </div>
            </div>
          )}

          {apolloError && <div className="err-banner">{apolloError}</div>}

          {enrollResult && (
            <div style={{
              background: "var(--gdim)", border: "1px solid var(--gb)",
              padding: "12px 16px", display: "flex", alignItems: "center",
              justifyContent: "space-between", gap: 12, flexWrap: "wrap",
            }}>
              <span style={{ fontSize: 13, color: "var(--green)", fontWeight: 600 }}>
                ✓ {enrollResult.enrolled} contact{enrollResult.enrolled !== 1 ? "s" : ""} enrolled
              </span>
              <Btn variant="green" onClick={() => setDetailTab("emails")} style={{ flexShrink: 0 }}>
                Write email sequence →
              </Btn>
            </div>
          )}

          {apolloSearching && <div style={{ ...section() }}><ProgressBar label="Searching…" stages={SEARCH_STAGES} /></div>}

          {!apolloSearching && apolloResults.length > 0 && (
            <>
              {apolloSource === "apollo_orgs" && (
                <div style={{
                  ...card({ padding: "10px 14px" }),
                  borderLeft: "3px solid var(--amber, #f59e0b)",
                  background: "rgba(245,158,11,0.06)",
                  fontSize: 12, color: "var(--fg)",
                  display: "flex", alignItems: "center", gap: 8,
                }}>
                  <span style={{ fontWeight: 700, color: "var(--amber, #f59e0b)" }}>⚠ Showing companies</span>
                  — people search requires an upgraded Apollo plan. Upgrade to get individual contacts with emails.
                </div>
              )}
              <div style={{ fontSize: 13, color: "var(--fm)" }}>
                {apolloTotal.toLocaleString()} {apolloSource === "apollo_orgs" ? "companies" : "contacts"} found
                {selectedContacts.size === 0 && apolloSource !== "apollo_orgs" && (
                  <span style={{ marginLeft: 8, color: "var(--blue)", fontWeight: 500 }}>
                    — check up to {MAX_CONFIRM} contacts below, then click Enroll
                  </span>
                )}
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 8 }}>
                {apolloResults.map(c => (
                  <ContactCard
                    key={c.apollo_id}
                    contact={c}
                    selected={selectedContacts.has(c.apollo_id)}
                    onToggle={() => toggleContact(c.apollo_id)}
                    disabled={selectedContacts.size >= MAX_CONFIRM && !selectedContacts.has(c.apollo_id)}
                  />
                ))}
              </div>

              {/* Sticky enroll bar — visible whenever contacts are selected */}
              {selectedContacts.size > 0 && (
                <div style={{
                  position: "sticky", bottom: 0,
                  background: "var(--surface)", borderTop: "2px solid var(--bb)",
                  padding: "12px 18px", display: "flex", alignItems: "center",
                  justifyContent: "space-between", gap: 12, flexWrap: "wrap",
                  boxShadow: "0 -4px 16px rgba(0,46,255,0.08)",
                }}>
                  <div>
                    <span style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)" }}>
                      {selectedContacts.size} contact{selectedContacts.size !== 1 ? "s" : ""} selected
                    </span>
                    <span style={{ fontSize: 12, color: "var(--fm)", marginLeft: 8 }}>
                      {selectedContacts.size < MAX_CONFIRM
                        ? `(up to ${MAX_CONFIRM - selectedContacts.size} more)`
                        : "max reached"}
                    </span>
                  </div>
                  <Btn variant="green" disabled={enrolling} onClick={confirmContacts} style={{ minWidth: 200 }}>
                    {enrolling ? "Enrolling…" : `Enroll ${selectedContacts.size} contact${selectedContacts.size !== 1 ? "s" : ""} →`}
                  </Btn>
                </div>
              )}
            </>
          )}

          {!apolloSearching && apolloResults.length === 0 && !apolloError && (
            <div style={{ ...card({ padding: "60px 20px", textAlign: "center" }) }}>
              <p style={{ fontSize: 14, color: "var(--fm)", margin: 0 }}>
                No contacts found. Try refining your search filters above.
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── Enrolled tab ────────────────────────────────────────────────── */}
      {detailTab === "enrolled" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {enrolledLoading ? (
            <div style={{ ...section() }}><ProgressBar label="Loading enrolled contacts…" /></div>
          ) : enrolled.length === 0 ? (
            <div style={{ ...card({ padding: "60px 20px", textAlign: "center" }) }}>
              <p style={{ fontSize: 14, color: "var(--fm)", margin: 0 }}>
                No contacts enrolled yet. Go to Find Contacts, select up to {MAX_CONFIRM}, and confirm.
              </p>
            </div>
          ) : (
            <>
              {activeCampaign.status === "draft" && (
                <div style={{
                  background: "var(--bdim)", border: "2px solid var(--bb)",
                  padding: "16px 20px", display: "flex", alignItems: "center",
                  justifyContent: "space-between", gap: 16, flexWrap: "wrap",
                }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: "var(--blue)" }}>
                      {enrolled.length} contact{enrolled.length !== 1 ? "s" : ""} ready to receive emails
                    </div>
                    <div style={{ fontSize: 12, color: "var(--fm)", marginTop: 3 }}>
                      Next: write your email sequence, then launch the campaign
                    </div>
                  </div>
                  <Btn variant="blue" onClick={() => setDetailTab("emails")} style={{ flexShrink: 0 }}>
                    Set up email sequence →
                  </Btn>
                </div>
              )}
              <div style={{ fontSize: 12, color: "var(--fm)", marginBottom: 4 }}>{enrolled.length} contacts enrolled</div>
              {enrolled.map(cc => {
                const c = cc.outreach_contacts;
                return (
                  <div key={cc.id} style={{
                    ...card({ padding: "12px 16px" }),
                    display: "grid", gridTemplateColumns: "1fr 130px 100px 120px", alignItems: "center", gap: 12,
                  }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg)" }}>
                        {c?.first_name} {c?.last_name}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--blue)", fontFamily: "var(--font-ibm-mono), monospace" }}>{c?.email || "—"}</div>
                      <div style={{ fontSize: 11, color: "var(--fm)" }}>{c?.title} · {c?.company_name}</div>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--fm)" }}>
                      Step {(cc.current_step || 0) + 1} of {activeCampaign.steps?.length || "?"}
                    </div>
                    <span className={statusPillClass(cc.status)}>{cc.status}</span>
                    <div style={{ fontSize: 11, color: "var(--fm)", fontFamily: "var(--font-ibm-mono), monospace" }}>
                      {cc.next_send_at
                        ? `next ${new Date(cc.next_send_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}`
                        : "—"}
                    </div>
                  </div>
                );
              })}
            </>
          )}
        </div>
      )}

      {/* ── Emails tab ──────────────────────────────────────────────────── */}
      {detailTab === "emails" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Controls */}
          <div style={{ display: "flex", gap: 8, justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: 8 }}>
              <Btn variant="blue" disabled={generatingSteps} onClick={generateSteps}>
                {generatingSteps ? "Generating…" : editingSteps.length ? "✦ Regenerate with AI" : "✦ Generate sequence with AI"}
              </Btn>
              {editingSteps.length > 0 && (
                <Btn variant="ghost" disabled={savingSteps} onClick={saveSteps}>
                  {savingSteps ? "Saving…" : "Save edits"}
                </Btn>
              )}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              {activeCampaign.status === "draft" && editingSteps.length > 0 && (
                <Btn variant="green" onClick={async () => { await updateCampaignStatus("active"); await sendBatch(); }}>
                  Launch &amp; Send →
                </Btn>
              )}
              {activeCampaign.status === "active" && (
                <>
                  <Btn variant="green" disabled={sendingBatch} onClick={sendBatch}>
                    {sendingBatch ? "Sending…" : "Send next batch →"}
                  </Btn>
                  <Btn variant="amber" onClick={() => updateCampaignStatus("paused")}>Pause</Btn>
                </>
              )}
              {activeCampaign.status === "paused" && (
                <Btn variant="green" onClick={async () => { await updateCampaignStatus("active"); await sendBatch(); }}>
                  Resume &amp; Send →
                </Btn>
              )}
            </div>
          </div>

          {batchResult && (
            <div style={{ background: batchResult.failed > 0 ? "var(--adim)" : "var(--gdim)", border: `1px solid ${batchResult.failed > 0 ? "var(--ab)" : "var(--gb)"}`, padding: "10px 14px", fontSize: 12 }}>
              <span style={{ color: "var(--green)" }}>{batchResult.sent} sent via Gmail</span>
              {batchResult.failed > 0 && <span style={{ color: "var(--amber)", marginLeft: 10 }}>{batchResult.failed} failed — check Gmail is connected in Integrations</span>}
            </div>
          )}

          {generatingSteps && <div style={{ ...section() }}><ProgressBar label="Generating email sequence with AI…" /></div>}

          {!generatingSteps && editingSteps.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {editingSteps.map((step, i) => (
                <div key={i} style={{ ...card({ padding: "16px 18px" }), display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span className="pill blue" style={{ flexShrink: 0 }}>Day {step.send_day}</span>
                    <input
                      value={step.subject}
                      onChange={e => setEditingSteps(prev => prev.map((s, idx) => idx === i ? { ...s, subject: e.target.value } : s))}
                      placeholder="Subject line…"
                      className="f-input"
                      style={{ flex: 1 }}
                    />
                  </div>
                  <textarea
                    value={step.body}
                    onChange={e => setEditingSteps(prev => prev.map((s, idx) => idx === i ? { ...s, body: e.target.value } : s))}
                    placeholder="Email body… Use {{first_name}}, {{company_name}}, {{title}} for personalisation"
                    className="f-input f-ta"
                    rows={7}
                    style={{ fontFamily: "var(--font-ibm-mono), monospace", lineHeight: 1.7 }}
                  />
                </div>
              ))}
            </div>
          )}

          {!generatingSteps && editingSteps.length === 0 && (
            <div style={{ ...card({ padding: "60px 20px", textAlign: "center" }) }}>
              <p style={{ fontSize: 14, color: "var(--fm)", margin: 0 }}>
                No steps yet. Click "Generate sequence with AI" above.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
