"use client";

import { useState, useEffect, useCallback, useRef } from "react";
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

// ── Helpers ────────────────────────────────────────────────────────────────────

function glass(extra?: React.CSSProperties): React.CSSProperties {
  return {
    background: "var(--glass)",
    backdropFilter: "var(--blur)",
    WebkitBackdropFilter: "var(--blur)",
    border: "1px solid var(--line)",
    borderRadius: 16,
    ...extra,
  };
}

const PILL: React.CSSProperties = {
  padding: "3px 10px", borderRadius: 20, fontSize: 11,
  fontFamily: "var(--font-mono)", display: "inline-block",
};

const STATUS_COLORS: Record<string, string> = {
  draft:     "rgba(255,255,255,0.12)",
  active:    "rgba(52,211,153,0.25)",
  paused:    "rgba(251,191,36,0.25)",
  completed: "rgba(96,165,250,0.2)",
};

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

function CheckGroup({ label, options, selected, onChange }: {
  label: string; options: { value: string; label: string }[];
  selected: string[]; onChange: (v: string[]) => void;
}) {
  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter(x => x !== v) : [...selected, v]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--fg-mute)", fontWeight: 600 }}>{label}</span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {options.map(o => (
          <button key={o.value} onClick={() => toggle(o.value)} style={{
            ...PILL,
            background: selected.includes(o.value) ? "rgba(96,165,250,0.2)" : "rgba(255,255,255,0.05)",
            border: `1px solid ${selected.includes(o.value) ? "rgba(96,165,250,0.4)" : "rgba(255,255,255,0.1)"}`,
            color: selected.includes(o.value) ? "#93c5fd" : "var(--fg-mute)",
            cursor: "pointer", transition: "all 0.12s",
          }}>{o.label}</button>
        ))}
      </div>
    </div>
  );
}

function ProgressBar({ label }: { label: string }) {
  return (
    <div style={{ padding: "36px 24px", textAlign: "center" }}>
      <div style={{ fontSize: 13, color: "rgba(255,255,255,0.45)", marginBottom: 16 }}>{label}</div>
      <div style={{ height: 3, background: "rgba(255,255,255,0.07)", overflow: "hidden", borderRadius: 2, maxWidth: 320, margin: "0 auto" }}>
        <div style={{
          height: "100%",
          background: "linear-gradient(90deg, transparent 0%, #60a5fa 40%, #a78bfa 70%, transparent 100%)",
          backgroundSize: "200% 100%",
          animation: "outreach-sweep 1.8s ease-in-out infinite",
        }} />
      </div>
    </div>
  );
}

function StatBadge({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div style={{ textAlign: "center", padding: "8px 12px", ...glass({ borderRadius: 10 }) }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: color || "var(--fg)", fontFamily: "var(--font-mono)" }}>{value}</div>
      <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--fg-mute)", marginTop: 2 }}>{label}</div>
    </div>
  );
}

// ── Campaign card ──────────────────────────────────────────────────────────────

function CampaignCard({ campaign, stats, onClick }: {
  campaign: Campaign; stats?: CampaignStats; onClick: () => void;
}) {
  const audience = campaign.target_audience;
  const hasAudience = audience && (audience.titles || audience.industries || audience.locations);
  return (
    <div onClick={onClick} style={{
      ...glass({ padding: "18px 20px", cursor: "pointer", borderRadius: 14 }),
      transition: "border-color 0.15s",
    }}
      onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.2)"}
      onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = "var(--line)"}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 600, color: "var(--fg)" }}>{campaign.name}</div>
          <div style={{ fontSize: 11, color: "var(--fg-mute)", marginTop: 2 }}>{campaign.from_email || "no sender"}</div>
        </div>
        <span style={{ ...PILL, background: STATUS_COLORS[campaign.status] || "rgba(255,255,255,0.1)", color: "var(--fg-dim)", flexShrink: 0 }}>
          {campaign.status}
        </span>
      </div>
      {hasAudience && (
        <div style={{ fontSize: 11, color: "var(--fg-mute)", marginBottom: 8 }}>
          {[audience.titles, audience.industries, audience.locations].filter(Boolean).join(" · ")}
        </div>
      )}
      {stats && stats.sent > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6 }}>
          <StatBadge label="Sent" value={stats.sent} />
          <StatBadge label="Opens" value={`${stats.open_rate}%`} color="#60a5fa" />
          <StatBadge label="Replies" value={`${stats.reply_rate}%`} color="#4ade80" />
        </div>
      )}
      <div style={{ marginTop: 8, fontSize: 10, color: "var(--fg-mute)" }}>
        {campaign.steps?.length || 0} email steps · {campaign.daily_limit}/day
      </div>
    </div>
  );
}

// ── Apollo contact card ────────────────────────────────────────────────────────

function ContactCard({ contact, selected, onToggle, disabled }: {
  contact: ApolloContact; selected: boolean; onToggle: () => void; disabled: boolean;
}) {
  return (
    <div
      onClick={disabled && !selected ? undefined : onToggle}
      style={{
        padding: "12px 14px", borderRadius: 12, cursor: disabled && !selected ? "not-allowed" : "pointer",
        background: selected ? "rgba(96,165,250,0.1)" : "rgba(255,255,255,0.03)",
        border: `1px solid ${selected ? "rgba(96,165,250,0.3)" : "rgba(255,255,255,0.07)"}`,
        transition: "all 0.1s", opacity: disabled && !selected ? 0.5 : 1,
        display: "flex", gap: 10, alignItems: "flex-start",
      }}
      onMouseEnter={e => { if (!disabled || selected) (e.currentTarget as HTMLElement).style.background = selected ? "rgba(96,165,250,0.14)" : "rgba(255,255,255,0.05)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = selected ? "rgba(96,165,250,0.1)" : "rgba(255,255,255,0.03)"; }}
    >
      <div style={{
        width: 16, height: 16, flexShrink: 0, marginTop: 2, borderRadius: 4,
        border: `1.5px solid ${selected ? "#60a5fa" : "rgba(255,255,255,0.2)"}`,
        background: selected ? "#60a5fa" : "transparent",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        {selected && <span style={{ fontSize: 9, color: "#000", fontWeight: 700 }}>✓</span>}
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>
            {contact.first_name} {contact.last_name}
          </span>
          {contact.has_email && (
            <span style={{ ...PILL, background: "rgba(52,211,153,0.15)", color: "#34d399", fontSize: 9, padding: "1px 6px" }}>
              email available
            </span>
          )}
          {contact.email && (
            <span style={{ ...PILL, background: "rgba(96,165,250,0.15)", color: "#93c5fd", fontSize: 9, padding: "1px 6px" }}>
              ✓ revealed
            </span>
          )}
        </div>
        <div style={{ fontSize: 11, color: "var(--fg-mute)", marginTop: 2 }}>{contact.title}</div>
        <div style={{ fontSize: 11, color: "var(--fg-dim)" }}>{contact.company_name}</div>
        {contact.email && <div style={{ fontSize: 10, color: "#93c5fd", marginTop: 2, fontFamily: "var(--font-mono)" }}>{contact.email}</div>}
      </div>
    </div>
  );
}

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
  const [creatingCampaign, setCreatingCampaign] = useState(false);

  // ── Find contacts tab ──────────────────────────────────────────────────────
  const [apolloResults, setApolloResults] = useState<ApolloContact[]>([]);
  const [apolloTotal, setApolloTotal] = useState(0);
  const [apolloSearching, setApolloSearching] = useState(false);
  const [apolloError, setApolloError] = useState("");
  const [selectedContacts, setSelectedContacts] = useState<Set<string>>(new Set());
  const [enrolling, setEnrolling] = useState(false);
  const [enrollResult, setEnrollResult] = useState<{ enrolled: number; credits_used: number } | null>(null);
  // Local audience refinement (editable from the campaign's target_audience)
  const [findAudience, setFindAudience] = useState<TargetAudience>(defaultAudience());
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
    apolloFetchedForRef.current = "";
    const audience = c.target_audience ?? defaultAudience();
    setFindAudience(audience);
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
      setApolloResults(data.contacts || []);
      setApolloTotal(data.total || 0);
    } catch (e) {
      setApolloError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setApolloSearching(false);
    }
  }, [founderId]);

  // Auto-search when entering the Find tab for a campaign
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

  // ── Confirm contacts (enrich + save + enroll) ──────────────────────────────

  const confirmContacts = async () => {
    if (!activeCampaign || selectedContacts.size === 0) return;
    setEnrolling(true);
    setEnrollResult(null);
    try {
      const toEnrich = apolloResults.filter(c => selectedContacts.has(c.apollo_id)).slice(0, MAX_CONFIRM);

      // Phase 1: enrich to reveal emails
      const enrichRes = await apiFetch(`${BASE}/outreach/enrich/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: founderId, contacts: toEnrich }),
      });
      const enrichData = await enrichRes.json();
      const enriched: ApolloContact[] = enrichData.enriched || [];
      const creditsUsed: number = enrichData.credits_used || 0;

      // Phase 2: save contacts to DB, get IDs back
      const saveRes = await apiFetch(`${BASE}/outreach/contacts/${founderId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contacts: enriched }),
      });
      const saveData = await saveRes.json();
      const savedContacts: { id: string }[] = saveData.contacts || [];
      const contactIds = savedContacts.map(c => c.id).filter(Boolean);

      // Phase 3: enroll in campaign
      if (contactIds.length > 0) {
        await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${activeCampaign.id}/contacts`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ contact_ids: contactIds }),
        });
      }

      setEnrollResult({ enrolled: contactIds.length, credits_used: creditsUsed });
      setSelectedContacts(new Set());
      // Update apollo results to show revealed emails
      setApolloResults(prev => prev.map(c => {
        const match = enriched.find(e => e.apollo_id === c.apollo_id);
        return match ? { ...c, ...match } : c;
      }));
      // Switch to enrolled tab to show results
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
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...newCampaign, target_audience: newAudience }),
      });
      const data = await res.json();
      setShowNewCampaign(false);
      setNewCampaign({ name: "", from_name: "", from_email: "", product_name: "", value_prop: "", daily_limit: 50 });
      setNewAudience(defaultAudience());
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
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${activeCampaign.id}/generate-steps`, {
        method: "POST",
      });
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
    } catch (e) {
      alert("Save failed: " + (e instanceof Error ? e.message : e));
    } finally {
      setSavingSteps(false);
    }
  };

  const sendBatch = async () => {
    if (!activeCampaign) return;
    setSendingBatch(true);
    setBatchResult(null);
    try {
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${activeCampaign.id}/send-batch`, {
        method: "POST",
      });
      const data = await res.json();
      setBatchResult({ sent: data.sent, failed: data.failed });
    } catch (e) {
      alert("Send failed: " + (e instanceof Error ? e.message : e));
    } finally {
      setSendingBatch(false);
    }
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

  // ── Toggle contact selection ───────────────────────────────────────────────

  const toggleContact = (apolloId: string) => {
    setSelectedContacts(prev => {
      const next = new Set(prev);
      if (next.has(apolloId)) {
        next.delete(apolloId);
      } else if (next.size < MAX_CONFIRM) {
        next.add(apolloId);
      }
      return next;
    });
  };

  const stats = activeCampaign ? campaignStats[activeCampaign.id] : null;

  // ══════════════════════════════════════════════════════════════════════════
  // RENDER
  // ══════════════════════════════════════════════════════════════════════════

  // ── Campaign list view ─────────────────────────────────────────────────────

  if (view === "campaigns") return (
    <div style={{ width: "100%", maxWidth: 1100, margin: "0 auto", display: "flex", flexDirection: "column", gap: 20 }}>
      <style>{`@keyframes outreach-sweep{0%{background-position:200% 0}100%{background-position:-200% 0}}`}</style>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>Outreach</h1>
          <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: "4px 0 0" }}>Create a campaign, find contacts from Apollo, send personalized emails</p>
        </div>
        <button onClick={() => setShowNewCampaign(true)} style={{
          padding: "0 20px", height: 38, fontSize: 13, fontWeight: 600,
          background: "rgba(96,165,250,0.15)", border: "1px solid rgba(96,165,250,0.3)",
          color: "#93c5fd", cursor: "pointer", borderRadius: 20, transition: "all .12s",
          whiteSpace: "nowrap",
        }}>
          + New Campaign
        </button>
      </div>

      {campaignsLoading ? (
        <ProgressBar label="Loading campaigns…" />
      ) : campaigns.length === 0 ? (
        <div style={{ ...glass({ padding: "60px 24px", textAlign: "center" }) }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📨</div>
          <p style={{ fontSize: 15, fontWeight: 600, color: "var(--fg)", margin: "0 0 6px" }}>No campaigns yet</p>
          <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: "0 0 20px" }}>Create one to start finding contacts and sending emails</p>
          <button onClick={() => setShowNewCampaign(true)} style={{
            padding: "8px 24px", fontSize: 13, fontWeight: 600,
            background: "rgba(96,165,250,0.15)", border: "1px solid rgba(96,165,250,0.3)",
            color: "#93c5fd", cursor: "pointer", borderRadius: 20,
          }}>Create first campaign</button>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 12 }}>
          {campaigns.map(c => (
            <CampaignCard key={c.id} campaign={c} stats={campaignStats[c.id]} onClick={() => enterCampaign(c)} />
          ))}
        </div>
      )}

      {/* New campaign modal */}
      {showNewCampaign && (
        <div style={{ position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,0.7)", backdropFilter: "blur(12px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24, overflowY: "auto" }}>
          <div style={{ ...glass({ padding: "28px 24px", width: "100%", maxWidth: 560, display: "flex", flexDirection: "column", gap: 0 }), maxHeight: "90vh", overflowY: "auto" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
              <span style={{ fontSize: 17, fontWeight: 700, color: "var(--fg)" }}>New Campaign</span>
              <button onClick={() => setShowNewCampaign(false)} style={{ background: "none", border: "none", color: "var(--fg-mute)", cursor: "pointer", fontSize: 18 }}>✕</button>
            </div>

            {/* Campaign basics */}
            <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--fg-mute)", fontWeight: 600, marginBottom: 12 }}>Campaign basics</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 20 }}>
              {[
                { label: "Campaign Name", key: "name", placeholder: "Q1 SaaS Outreach" },
                { label: "From Name", key: "from_name", placeholder: "Alex from Astra" },
                { label: "From Email", key: "from_email", placeholder: "alex@yourcompany.com" },
                { label: "Product Name", key: "product_name", placeholder: "Astra" },
                { label: "Value Proposition", key: "value_prop", placeholder: "Helps founders build startups 10x faster" },
              ].map(f => (
                <div key={f.key}>
                  <label style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)", marginBottom: 4, display: "block" }}>{f.label}</label>
                  <input
                    value={(newCampaign as Record<string, string | number>)[f.key] as string}
                    onChange={e => setNewCampaign(p => ({ ...p, [f.key]: e.target.value }))}
                    placeholder={f.placeholder}
                    className="site-input"
                    style={{ padding: "8px 12px", fontSize: 13, width: "100%", boxSizing: "border-box" }}
                  />
                </div>
              ))}
            </div>

            {/* Target audience */}
            <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--fg-mute)", fontWeight: 600, marginBottom: 12 }}>Target audience (for Apollo search)</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 20 }}>
              {[
                { label: "Job Titles", key: "titles", placeholder: "CEO, CTO, Founder, Head of Growth" },
                { label: "Locations", key: "locations", placeholder: "United States, United Kingdom" },
                { label: "Industries", key: "industries", placeholder: "SaaS, Fintech, E-commerce" },
                { label: "Keywords", key: "keywords", placeholder: "startup, growth, scale" },
              ].map(f => (
                <div key={f.key}>
                  <label style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)", marginBottom: 4, display: "block" }}>{f.label}</label>
                  <input
                    value={(newAudience as unknown as Record<string, string>)[f.key] ?? ""}
                    onChange={e => setNewAudience(a => ({ ...a, [f.key]: e.target.value }))}
                    placeholder={f.placeholder}
                    className="site-input"
                    style={{ padding: "8px 12px", fontSize: 13, width: "100%", boxSizing: "border-box" }}
                  />
                </div>
              ))}
              <CheckGroup label="Seniority" options={SENIORITY_OPTIONS} selected={newAudience.seniorities} onChange={v => setNewAudience(a => ({ ...a, seniorities: v }))} />
              <CheckGroup label="Company Size" options={COMPANY_SIZE_OPTIONS} selected={newAudience.company_sizes} onChange={v => setNewAudience(a => ({ ...a, company_sizes: v }))} />
            </div>

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button onClick={() => setShowNewCampaign(false)} style={{ padding: "0 16px", height: 36, fontSize: 13, background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.12)", color: "var(--fg-mute)", cursor: "pointer", borderRadius: 10 }}>
                Cancel
              </button>
              <button
                onClick={createCampaign}
                disabled={creatingCampaign || !newCampaign.name.trim()}
                style={{ padding: "0 20px", height: 36, fontSize: 13, fontWeight: 600, background: "rgba(96,165,250,0.15)", border: "1px solid rgba(96,165,250,0.3)", color: "#93c5fd", cursor: "pointer", borderRadius: 10, opacity: creatingCampaign || !newCampaign.name.trim() ? 0.5 : 1 }}
              >
                {creatingCampaign ? "Creating…" : "Create & Find Contacts →"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  // ── Campaign detail view ───────────────────────────────────────────────────

  if (!activeCampaign) return null;

  const DETAIL_TABS: { key: DetailTab; label: string }[] = [
    { key: "find", label: "Find Contacts" },
    { key: "enrolled", label: "Enrolled" },
    { key: "emails", label: "Emails" },
  ];

  const TAB_BTN = (t: typeof DETAIL_TABS[0]): React.CSSProperties => ({
    display: "flex", alignItems: "center", gap: 6,
    padding: "7px 16px", borderRadius: 20, fontSize: 13, fontWeight: 500,
    cursor: "pointer", transition: "all 0.12s",
    border: detailTab === t.key ? "1px solid rgba(96,165,250,0.35)" : "1px solid transparent",
    background: detailTab === t.key ? "rgba(96,165,250,0.12)" : "transparent",
    color: detailTab === t.key ? "#93c5fd" : "var(--fg-mute)",
  });

  return (
    <div style={{ width: "100%", maxWidth: 1100, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
      <style>{`@keyframes outreach-sweep{0%{background-position:200% 0}100%{background-position:-200% 0}}`}</style>

      {/* Detail header */}
      <div>
        <button
          onClick={() => { setView("campaigns"); setActiveCampaign(null); loadCampaigns(); }}
          style={{ background: "none", border: "none", color: "var(--fg-mute)", cursor: "pointer", fontSize: 12, padding: 0, marginBottom: 10, display: "flex", alignItems: "center", gap: 5 }}
        >
          ← All campaigns
        </button>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>{activeCampaign.name}</h1>
              <span style={{ ...PILL, background: STATUS_COLORS[activeCampaign.status] || "rgba(255,255,255,0.1)", color: "var(--fg-dim)" }}>
                {activeCampaign.status}
              </span>
            </div>
            <div style={{ fontSize: 12, color: "var(--fg-mute)", marginTop: 3 }}>
              {activeCampaign.from_name} · {activeCampaign.from_email || "no sender set"} · {activeCampaign.daily_limit}/day
            </div>
          </div>
          {stats && stats.sent > 0 && (
            <div style={{ display: "flex", gap: 8 }}>
              <StatBadge label="Sent" value={stats.sent} />
              <StatBadge label="Opens" value={`${stats.open_rate}%`} color="#60a5fa" />
              <StatBadge label="Replies" value={`${stats.reply_rate}%`} color="#4ade80" />
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 14 }}>
          {DETAIL_TABS.map(t => <button key={t.key} onClick={() => setDetailTab(t.key)} style={TAB_BTN(t)}>{t.label}</button>)}
        </div>
      </div>

      {/* ── Find Contacts tab ─────────────────────────────────────────────── */}
      {detailTab === "find" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Audience summary + refine toggle */}
          <div style={{ ...glass({ padding: "14px 18px" }), display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div style={{ fontSize: 13, color: "var(--fg-dim)" }}>
              {[findAudience.titles, findAudience.industries, findAudience.locations, findAudience.keywords]
                .filter(Boolean).join(" · ") || "No audience filters set — showing broad results"}
            </div>
            <button
              onClick={() => setShowRefine(r => !r)}
              style={{ fontSize: 12, color: "#60a5fa", background: "none", border: "1px solid rgba(96,165,250,0.25)", padding: "4px 12px", borderRadius: 20, cursor: "pointer", flexShrink: 0 }}
            >
              {showRefine ? "Hide filters" : "Refine search"}
            </button>
          </div>

          {/* Refine panel */}
          {showRefine && (
            <div style={{ ...glass({ padding: "16px 18px" }), display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                {[
                  { label: "Job Titles", key: "titles", placeholder: "CEO, CTO, Founder" },
                  { label: "Locations", key: "locations", placeholder: "United States" },
                  { label: "Industries", key: "industries", placeholder: "SaaS, Fintech" },
                  { label: "Keywords", key: "keywords", placeholder: "startup, growth" },
                ].map(f => (
                  <div key={f.key}>
                    <label style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)", marginBottom: 4, display: "block" }}>{f.label}</label>
                    <input
                      value={(findAudience as unknown as Record<string, string>)[f.key] ?? ""}
                      onChange={e => setFindAudience(a => ({ ...a, [f.key]: e.target.value }))}
                      placeholder={f.placeholder}
                      className="site-input"
                      style={{ padding: "7px 10px", fontSize: 12, width: "100%", boxSizing: "border-box" }}
                    />
                  </div>
                ))}
              </div>
              <CheckGroup label="Seniority" options={SENIORITY_OPTIONS} selected={findAudience.seniorities} onChange={v => setFindAudience(a => ({ ...a, seniorities: v }))} />
              <CheckGroup label="Company Size" options={COMPANY_SIZE_OPTIONS} selected={findAudience.company_sizes} onChange={v => setFindAudience(a => ({ ...a, company_sizes: v }))} />
              <button
                onClick={() => {
                  apolloFetchedForRef.current = ""; // clear cache so search runs
                  runApolloSearch(findAudience);
                  setShowRefine(false);
                }}
                disabled={apolloSearching}
                style={{ alignSelf: "flex-end", padding: "6px 20px", fontSize: 13, fontWeight: 600, background: "rgba(96,165,250,0.15)", border: "1px solid rgba(96,165,250,0.3)", color: "#93c5fd", cursor: "pointer", borderRadius: 20 }}
              >
                {apolloSearching ? "Searching…" : "Re-search →"}
              </button>
            </div>
          )}

          {/* Error */}
          {apolloError && (
            <div style={{ padding: "10px 14px", background: "rgba(248,113,113,0.08)", border: "1px solid rgba(248,113,113,0.2)", borderRadius: 10, fontSize: 12, color: "#f87171" }}>
              {apolloError}
            </div>
          )}

          {/* Enroll result banner */}
          {enrollResult && (
            <div style={{ padding: "10px 14px", background: "rgba(52,211,153,0.08)", border: "1px solid rgba(52,211,153,0.2)", borderRadius: 10, fontSize: 12, color: "#34d399" }}>
              ✓ Enrolled {enrollResult.enrolled} contacts · used {enrollResult.credits_used} credits
            </div>
          )}

          {/* Searching state */}
          {apolloSearching && (
            <div style={{ ...glass() }}>
              <ProgressBar label="Searching Apollo for matching contacts…" />
            </div>
          )}

          {/* Results */}
          {!apolloSearching && apolloResults.length > 0 && (
            <>
              {/* Selection header */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                <span style={{ fontSize: 13, color: "var(--fg-mute)" }}>
                  {apolloTotal.toLocaleString()} contacts found · {selectedContacts.size}/{MAX_CONFIRM} selected
                </span>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  {selectedContacts.size > 0 && (
                    <span style={{ fontSize: 11, color: "var(--fg-mute)" }}>
                      Uses {selectedContacts.size} credit{selectedContacts.size !== 1 ? "s" : ""} to reveal emails
                    </span>
                  )}
                  <button
                    onClick={confirmContacts}
                    disabled={enrolling || selectedContacts.size === 0}
                    style={{
                      padding: "6px 20px", fontSize: 13, fontWeight: 600,
                      background: selectedContacts.size > 0 ? "rgba(52,211,153,0.15)" : "rgba(255,255,255,0.05)",
                      border: `1px solid ${selectedContacts.size > 0 ? "rgba(52,211,153,0.3)" : "rgba(255,255,255,0.1)"}`,
                      color: selectedContacts.size > 0 ? "#34d399" : "var(--fg-mute)",
                      cursor: enrolling || selectedContacts.size === 0 ? "not-allowed" : "pointer",
                      borderRadius: 20, opacity: enrolling ? 0.7 : 1,
                    }}
                  >
                    {enrolling ? "Enriching & enrolling…" : selectedContacts.size > 0 ? `Confirm ${selectedContacts.size} contact${selectedContacts.size !== 1 ? "s" : ""} →` : "Select contacts below"}
                  </button>
                </div>
              </div>

              {/* Contact grid */}
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

              {selectedContacts.size >= MAX_CONFIRM && (
                <div style={{ textAlign: "center", fontSize: 12, color: "var(--fg-mute)", padding: "4px 0" }}>
                  Max {MAX_CONFIRM} contacts selected. Confirm these or deselect to pick different ones.
                </div>
              )}
            </>
          )}

          {!apolloSearching && apolloResults.length === 0 && !apolloError && (
            <div style={{ ...glass({ padding: "60px 20px", textAlign: "center" }) }}>
              <p style={{ fontSize: 14, color: "var(--fg-mute)", margin: 0 }}>
                No contacts found. Try refining your search filters above.
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── Enrolled tab ────────────────────────────────────────────────── */}
      {detailTab === "enrolled" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {enrolledLoading ? (
            <ProgressBar label="Loading enrolled contacts…" />
          ) : enrolled.length === 0 ? (
            <div style={{ ...glass({ padding: "60px 20px", textAlign: "center" }) }}>
              <p style={{ fontSize: 14, color: "var(--fg-mute)", margin: 0 }}>
                No contacts enrolled yet. Go to Find Contacts, select up to {MAX_CONFIRM}, and confirm.
              </p>
            </div>
          ) : (
            <>
              <div style={{ fontSize: 13, color: "var(--fg-mute)" }}>{enrolled.length} contacts enrolled</div>
              {enrolled.map(cc => {
                const c = cc.outreach_contacts;
                return (
                  <div key={cc.id} style={{
                    ...glass({ padding: "12px 16px", borderRadius: 12 }),
                    display: "grid", gridTemplateColumns: "1fr 140px 120px 110px", alignItems: "center", gap: 12,
                  }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)" }}>
                        {c?.first_name} {c?.last_name}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--fg-mute)" }}>{c?.email || "—"}</div>
                      <div style={{ fontSize: 11, color: "var(--fg-dim)" }}>{c?.title} · {c?.company_name}</div>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--fg-mute)" }}>
                      Step {(cc.current_step || 0) + 1} of {activeCampaign.steps?.length || "?"}
                    </div>
                    <div>
                      <span style={{ ...PILL, background: STATUS_COLORS[cc.status] || "rgba(255,255,255,0.1)", color: "var(--fg-dim)" }}>
                        {cc.status}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--fg-mute)" }}>
                      {cc.next_send_at ? `next: ${new Date(cc.next_send_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}` : "—"}
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
          {/* Actions row */}
          <div style={{ display: "flex", gap: 8, justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={generateSteps} disabled={generatingSteps} style={{
                padding: "0 18px", height: 36, fontSize: 13, fontWeight: 500,
                background: "rgba(167,139,250,0.12)", border: "1px solid rgba(167,139,250,0.25)",
                color: "#a78bfa", cursor: "pointer", borderRadius: 20,
                opacity: generatingSteps ? 0.7 : 1,
              }}>
                {generatingSteps ? "Generating…" : editingSteps.length ? "✦ Regenerate with AI" : "✦ Generate sequence with AI"}
              </button>
              {editingSteps.length > 0 && (
                <button onClick={saveSteps} disabled={savingSteps} style={{
                  padding: "0 18px", height: 36, fontSize: 13,
                  background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.12)",
                  color: "var(--fg-mute)", cursor: "pointer", borderRadius: 20,
                  opacity: savingSteps ? 0.7 : 1,
                }}>
                  {savingSteps ? "Saving…" : "Save edits"}
                </button>
              )}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              {activeCampaign.status === "draft" && editingSteps.length > 0 && (
                <button onClick={async () => { await updateCampaignStatus("active"); await sendBatch(); }} style={{
                  padding: "0 20px", height: 36, fontSize: 13, fontWeight: 600,
                  background: "rgba(52,211,153,0.15)", border: "1px solid rgba(52,211,153,0.3)",
                  color: "#34d399", cursor: "pointer", borderRadius: 20,
                }}>
                  Launch & Send →
                </button>
              )}
              {activeCampaign.status === "active" && (
                <>
                  <button onClick={sendBatch} disabled={sendingBatch} style={{
                    padding: "0 20px", height: 36, fontSize: 13, fontWeight: 600,
                    background: "rgba(52,211,153,0.15)", border: "1px solid rgba(52,211,153,0.3)",
                    color: "#34d399", cursor: sendingBatch ? "not-allowed" : "pointer", borderRadius: 20, opacity: sendingBatch ? 0.7 : 1,
                  }}>
                    {sendingBatch ? "Sending…" : "Send next batch →"}
                  </button>
                  <button onClick={() => updateCampaignStatus("paused")} style={{
                    padding: "0 16px", height: 36, fontSize: 13,
                    background: "rgba(251,191,36,0.08)", border: "1px solid rgba(251,191,36,0.25)",
                    color: "#fbbf24", cursor: "pointer", borderRadius: 20,
                  }}>Pause</button>
                </>
              )}
              {activeCampaign.status === "paused" && (
                <button onClick={async () => { await updateCampaignStatus("active"); await sendBatch(); }} style={{
                  padding: "0 20px", height: 36, fontSize: 13, fontWeight: 600,
                  background: "rgba(52,211,153,0.15)", border: "1px solid rgba(52,211,153,0.3)",
                  color: "#34d399", cursor: "pointer", borderRadius: 20,
                }}>
                  Resume & Send →
                </button>
              )}
            </div>
          </div>

          {/* Batch send result */}
          {batchResult && (
            <div style={{ padding: "10px 14px", borderRadius: 10, background: batchResult.failed > 0 ? "rgba(251,191,36,0.08)" : "rgba(52,211,153,0.08)", border: `1px solid ${batchResult.failed > 0 ? "rgba(251,191,36,0.2)" : "rgba(52,211,153,0.2)"}`, fontSize: 12 }}>
              <span style={{ color: "#4ade80" }}>{batchResult.sent} sent via Gmail</span>
              {batchResult.failed > 0 && <span style={{ color: "#fbbf24", marginLeft: 10 }}>{batchResult.failed} failed — check Gmail is connected in Integrations</span>}
            </div>
          )}

          {/* Email steps */}
          {generatingSteps && <ProgressBar label="Generating email sequence with AI…" />}

          {!generatingSteps && editingSteps.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {editingSteps.map((step, i) => (
                <div key={i} style={{ ...glass({ padding: "16px 18px", borderRadius: 12 }), display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ ...PILL, background: "rgba(96,165,250,0.15)", color: "#93c5fd", flexShrink: 0 }}>
                      Day {step.send_day}
                    </span>
                    <input
                      value={step.subject}
                      onChange={e => setEditingSteps(prev => prev.map((s, idx) => idx === i ? { ...s, subject: e.target.value } : s))}
                      placeholder="Subject line…"
                      className="site-input"
                      style={{ flex: 1, padding: "6px 12px", fontSize: 13, fontWeight: 500 }}
                    />
                  </div>
                  <textarea
                    value={step.body}
                    onChange={e => setEditingSteps(prev => prev.map((s, idx) => idx === i ? { ...s, body: e.target.value } : s))}
                    placeholder="Email body… Use {{first_name}}, {{company_name}}, {{title}} for personalization"
                    className="site-input"
                    rows={7}
                    style={{ fontSize: 12, lineHeight: 1.7, resize: "vertical", padding: "10px 12px", fontFamily: "var(--font-mono)" }}
                  />
                </div>
              ))}
            </div>
          )}

          {!generatingSteps && editingSteps.length === 0 && (
            <div style={{ ...glass({ padding: "60px 20px", textAlign: "center" }) }}>
              <p style={{ fontSize: 14, color: "var(--fg-mute)", margin: 0 }}>
                No email steps yet. Click "Generate sequence with AI" above.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
