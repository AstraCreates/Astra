"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { apiFetch } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────────

interface Contact {
  id?: string;
  apollo_id?: string;
  first_name: string;
  last_name: string;
  email: string;
  title: string;
  company_name: string;
  company_domain?: string;
  company_industry?: string;
  company_size?: string;
  funding_stage?: string;
  company_funding_stage?: string;
  seniority?: string;
  linkedin_url?: string;
  city?: string;
  country?: string;
  status?: string;
  source?: string;
}

interface ContactList {
  id: string;
  name: string;
  description: string;
  contact_count: number;
  created_at: string;
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
  created_at: string;
}

interface CampaignStep {
  subject: string;
  body: string;
  send_day: number;
  type?: string;
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

// ── Styles ────────────────────────────────────────────────────────────────────

function glass(extra?: React.CSSProperties): React.CSSProperties {
  return {
    background: "var(--glass)",
    backdropFilter: "var(--blur)",
    WebkitBackdropFilter: "var(--blur)",
    border: "1px solid var(--line)",
    borderRadius: 20,
    ...extra,
  };
}

const PILL: React.CSSProperties = {
  padding: "4px 12px", borderRadius: 20, fontSize: 11,
  fontFamily: "var(--font-mono)", display: "inline-block",
};

const STATUS_COLORS: Record<string, string> = {
  new: "rgba(255,255,255,0.15)",
  contacted: "rgba(96,165,250,0.25)",
  replied: "rgba(52,211,153,0.25)",
  meeting: "rgba(167,139,250,0.25)",
  won: "rgba(74,222,128,0.25)",
  lost: "rgba(248,113,113,0.2)",
  unsubscribed: "rgba(255,255,255,0.08)",
};

const CAMPAIGN_STATUS_COLORS: Record<string, string> = {
  draft: "rgba(255,255,255,0.12)",
  active: "rgba(52,211,153,0.25)",
  paused: "rgba(251,191,36,0.25)",
  completed: "rgba(96,165,250,0.2)",
};

// ── Filter options ────────────────────────────────────────────────────────────

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

const FUNDING_OPTIONS = [
  { value: "seed", label: "Seed" },
  { value: "series_a", label: "Series A" },
  { value: "series_b", label: "Series B" },
  { value: "series_c", label: "Series C" },
  { value: "series_d_plus", label: "Series D+" },
  { value: "bootstrapped", label: "Bootstrapped" },
];

// ── Checkbox group ────────────────────────────────────────────────────────────

function CheckGroup({ label, options, selected, onChange }: {
  label: string;
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter(x => x !== v) : [...selected, v]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--fg-mute)" }}>{label}</span>
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

// ── Stat badge ────────────────────────────────────────────────────────────────

function StatBadge({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div style={{ textAlign: "center", padding: "8px 12px", ...glass({ borderRadius: 12 }) }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: color || "var(--fg)", fontFamily: "var(--font-mono)" }}>{value}</div>
      <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--fg-mute)", marginTop: 2 }}>{label}</div>
    </div>
  );
}

// ── Contact row ───────────────────────────────────────────────────────────────

function ContactRow({ contact, selected, onSelect }: {
  contact: Contact; selected: boolean; onSelect: (c: Contact) => void;
}) {
  return (
    <div
      onClick={() => onSelect(contact)}
      style={{
        display: "grid", gridTemplateColumns: "28px 1fr 1fr 120px 100px 80px",
        alignItems: "center", gap: 12, padding: "10px 14px",
        borderRadius: 12, cursor: "pointer",
        background: selected ? "rgba(96,165,250,0.08)" : "transparent",
        border: `1px solid ${selected ? "rgba(96,165,250,0.2)" : "transparent"}`,
        transition: "all 0.1s",
      }}
      onMouseEnter={e => { if (!selected) (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.03)"; }}
      onMouseLeave={e => { if (!selected) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
    >
      <div
        onClick={e => { e.stopPropagation(); onSelect(contact); }}
        style={{
          width: 16, height: 16, borderRadius: 4,
          border: `1.5px solid ${selected ? "#60a5fa" : "rgba(255,255,255,0.2)"}`,
          background: selected ? "#60a5fa" : "transparent",
          display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer",
        }}
      >
        {selected && <span style={{ fontSize: 10, color: "#000", fontWeight: 700 }}>✓</span>}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--fg)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {contact.first_name} {contact.last_name}
        </div>
        <div style={{ fontSize: 11, color: "var(--fg-mute)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {contact.email || "email hidden"}
        </div>
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12, color: "var(--fg-dim)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {contact.title}
        </div>
        <div style={{ fontSize: 11, color: "var(--fg-mute)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {contact.company_name}
        </div>
      </div>
      <div style={{ fontSize: 11, color: "var(--fg-mute)" }}>
        {contact.company_industry || contact.company_size || "—"}
      </div>
      <div style={{ fontSize: 11, color: "var(--fg-mute)" }}>
        {contact.city || contact.country || "—"}
      </div>
      <div>
        <span style={{
          ...PILL,
          background: STATUS_COLORS[contact.status || "new"] || "rgba(255,255,255,0.1)",
          color: "var(--fg-dim)", fontSize: 10,
        }}>{contact.status || "new"}</span>
      </div>
    </div>
  );
}

// ── Campaign card ─────────────────────────────────────────────────────────────

function CampaignCard({ campaign, stats, onClick }: {
  campaign: Campaign; stats?: CampaignStats; onClick: () => void;
}) {
  return (
    <div onClick={onClick} style={{
      ...glass({ padding: "16px 18px", cursor: "pointer" }),
      transition: "border-color 0.15s",
    }}
      onMouseEnter={e => (e.currentTarget as HTMLElement).style.borderColor = "rgba(255,255,255,0.18)"}
      onMouseLeave={e => (e.currentTarget as HTMLElement).style.borderColor = "var(--line)"}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8, marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)" }}>{campaign.name}</div>
          <div style={{ fontSize: 11, color: "var(--fg-mute)", marginTop: 2 }}>{campaign.from_email || "no sender set"}</div>
        </div>
        <span style={{
          ...PILL,
          background: CAMPAIGN_STATUS_COLORS[campaign.status] || "rgba(255,255,255,0.1)",
          color: "var(--fg-dim)",
        }}>{campaign.status}</span>
      </div>
      {stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6, marginTop: 8 }}>
          <StatBadge label="Sent" value={stats.sent} />
          <StatBadge label="Opens" value={`${stats.open_rate}%`} color="#60a5fa" />
          <StatBadge label="Replies" value={`${stats.reply_rate}%`} color="#4ade80" />
        </div>
      )}
      <div style={{ marginTop: 10, fontSize: 11, color: "var(--fg-mute)" }}>
        {campaign.steps?.length || 0} steps · {campaign.daily_limit}/day · {campaign.send_provider}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

type Tab = "search" | "contacts" | "campaigns" | "lists";

export default function OutreachPage() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;

  const [tab, setTab] = useState<Tab>("search");

  // ── Find contacts state ───────────────────────────────────────────────────
  const [targetAudience, setTargetAudience] = useState("");
  const [findingContacts, setFindingContacts] = useState(false);
  const [findResult, setFindResult] = useState<{ contacts_found: number; contacts_stored: number; domains_searched: string[]; error?: string } | null>(null);

  // ── Search / filter state ─────────────────────────────────────────────────
  const [searchTitles, setSearchTitles] = useState("");
  const [searchLocations, setSearchLocations] = useState("");
  const [searchIndustries, setSearchIndustries] = useState("");
  const [selectedSeniorities, setSelectedSeniorities] = useState<string[]>([]);
  const [selectedSizes, setSelectedSizes] = useState<string[]>([]);
  const [searchResults, setSearchResults] = useState<Contact[]>([]);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchPage, setSearchPage] = useState(1);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [selectedContacts, setSelectedContacts] = useState<Set<string>>(new Set());

  // ── Contacts state ────────────────────────────────────────────────────────
  const [savedContacts, setSavedContacts] = useState<Contact[]>([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  const [contactStatusFilter, setContactStatusFilter] = useState("");

  // ── Lists state ───────────────────────────────────────────────────────────
  const [lists, setLists] = useState<ContactList[]>([]);
  const [newListName, setNewListName] = useState("");
  const [creatingList, setCreatingList] = useState(false);

  // ── Campaigns state ───────────────────────────────────────────────────────
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [campaignStats, setCampaignStats] = useState<Record<string, CampaignStats>>({});
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);
  const [showNewCampaign, setShowNewCampaign] = useState(false);
  const [campaignsLoading, setCampaignsLoading] = useState(false);
  const [newCampaign, setNewCampaign] = useState({
    name: "", from_name: "", from_email: "", product_name: "", value_prop: "", daily_limit: 50,
  });
  const [generatingSteps, setGeneratingSteps] = useState(false);
  const [editingSteps, setEditingSteps] = useState<CampaignStep[]>([]);
  const [savingSteps, setSavingSteps] = useState(false);
  const [sendingBatch, setSendingBatch] = useState(false);
  const [batchResult, setBatchResult] = useState<{ sent: number; failed: number } | null>(null);


  // ── Load data ─────────────────────────────────────────────────────────────

  const loadContacts = useCallback(async () => {
    setContactsLoading(true);
    try {
      const params = new URLSearchParams({ founder_id: founderId });
      if (contactStatusFilter) params.set("status", contactStatusFilter);
      const res = await apiFetch(`${BASE}/outreach/contacts/${founderId}?${params}`);
      const data = await res.json();
      setSavedContacts(data.contacts || []);
    } catch { /* ignore */ }
    finally { setContactsLoading(false); }
  }, [founderId, contactStatusFilter]);

  const loadLists = useCallback(async () => {
    try {
      const res = await apiFetch(`${BASE}/outreach/lists/${founderId}`);
      const data = await res.json();
      setLists(data.lists || []);
    } catch { /* ignore */ }
  }, [founderId]);

  const loadCampaigns = useCallback(async () => {
    setCampaignsLoading(true);
    try {
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}`);
      const data = await res.json();
      const camps: Campaign[] = data.campaigns || [];
      setCampaigns(camps);
      // Load stats for each campaign in parallel
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

  useEffect(() => {
    if (tab === "contacts") loadContacts();
    if (tab === "lists") loadLists();
    if (tab === "campaigns") loadCampaigns();
  }, [tab, loadContacts, loadLists, loadCampaigns]);


  // ── Search ────────────────────────────────────────────────────────────────

  const runSearch = async (page = 1) => {
    setSearching(true);
    setSearchError("");
    setSearchPage(page);
    try {
      const params = new URLSearchParams({
        founder_id: founderId,
        page: String(page),
        per_page: "25",
      });
      if (searchTitles) params.set("titles", searchTitles);
      if (searchLocations) params.set("locations", searchLocations);
      if (searchIndustries) params.set("industries", searchIndustries);
      if (selectedSeniorities.length) params.set("seniorities", selectedSeniorities.join(","));
      if (selectedSizes.length) params.set("company_sizes", selectedSizes.join(","));

      const res = await apiFetch(`${BASE}/outreach/search/people?${params}`);
      const data = await res.json();
      if (data.error) { setSearchError(JSON.stringify(data.error)); return; }
      setSearchResults(data.contacts || []);
      setSearchTotal(data.total || 0);
      setSelectedContacts(new Set());
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setSearching(false);
    }
  };

  const findContacts = async () => {
    if (!targetAudience.trim()) return;
    setFindingContacts(true);
    setFindResult(null);
    setSearchError("");
    try {
      const res = await apiFetch(`${BASE}/outreach/find-contacts/${founderId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_audience: targetAudience.trim(), limit: 8 }),
      });
      const data = await res.json();
      setFindResult(data);
      // Display contacts directly from API response — no Supabase needed
      if (data.contacts && data.contacts.length > 0) {
        setSearchResults(data.contacts);
        setSearchTotal(data.contacts.length);
        setSelectedContacts(new Set());
      }
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : "Failed to find contacts");
    } finally {
      setFindingContacts(false);
    }
  };

  const toggleContact = (c: Contact) => {
    const key = c.apollo_id || c.email;
    setSelectedContacts(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const selectAll = () => {
    if (selectedContacts.size === searchResults.length) {
      setSelectedContacts(new Set());
    } else {
      setSelectedContacts(new Set(searchResults.map(c => c.apollo_id || c.email)));
    }
  };

  const saveSelected = async (listName?: string) => {
    const toSave = searchResults.filter(c => selectedContacts.has(c.apollo_id || c.email));
    if (!toSave.length) return;
    try {
      const res = await apiFetch(`${BASE}/outreach/contacts/${founderId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contacts: toSave }),
      });
      const data = await res.json();
      if (listName) {
        // Also create a list
        const savedRes = await apiFetch(`${BASE}/outreach/contacts/${founderId}`);
        const savedData = await savedRes.json();
        const ids = (savedData.contacts || [])
          .filter((c: Contact) => toSave.some(s => s.email === c.email))
          .map((c: Contact) => c.id);
        await apiFetch(`${BASE}/outreach/lists/${founderId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: listName, contact_ids: ids }),
        });
        await loadLists();
      }
      alert(`Saved ${data.saved} contacts`);
    } catch (e) {
      alert("Save failed: " + (e instanceof Error ? e.message : e));
    }
  };

  // ── Create campaign ───────────────────────────────────────────────────────

  const createCampaign = async () => {
    try {
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newCampaign),
      });
      const data = await res.json();
      setShowNewCampaign(false);
      setNewCampaign({ name: "", from_name: "", from_email: "", product_name: "", value_prop: "", daily_limit: 50 });
      await loadCampaigns();
      setSelectedCampaign(data);
    } catch (e) {
      alert("Failed: " + (e instanceof Error ? e.message : e));
    }
  };

  const openCampaign = (c: Campaign) => {
    setSelectedCampaign(c);
    setEditingSteps(c.steps ? JSON.parse(JSON.stringify(c.steps)) : []);
    setBatchResult(null);
  };

  const generateSteps = async (campaignId: string) => {
    setGeneratingSteps(true);
    try {
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${campaignId}/generate-steps`, {
        method: "POST",
      });
      const data = await res.json();
      setSelectedCampaign(prev => prev ? { ...prev, steps: data.steps } : prev);
      setEditingSteps(data.steps ? JSON.parse(JSON.stringify(data.steps)) : []);
      await loadCampaigns();
    } catch { /* ignore */ }
    finally { setGeneratingSteps(false); }
  };

  const saveSteps = async () => {
    if (!selectedCampaign) return;
    setSavingSteps(true);
    try {
      await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${selectedCampaign.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ steps: editingSteps }),
      });
      setSelectedCampaign(prev => prev ? { ...prev, steps: editingSteps } : prev);
      await loadCampaigns();
    } catch (e) {
      alert("Save failed: " + (e instanceof Error ? e.message : e));
    } finally {
      setSavingSteps(false);
    }
  };

  const sendBatch = async () => {
    if (!selectedCampaign) return;
    setSendingBatch(true);
    setBatchResult(null);
    try {
      const res = await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${selectedCampaign.id}/send-batch`, {
        method: "POST",
      });
      const data = await res.json();
      setBatchResult({ sent: data.sent, failed: data.failed });
      await loadCampaigns();
    } catch (e) {
      alert("Send failed: " + (e instanceof Error ? e.message : e));
    } finally {
      setSendingBatch(false);
    }
  };

  const launchCampaign = async (campaignId: string) => {
    await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${campaignId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "active" }),
    });
    setSelectedCampaign(prev => prev ? { ...prev, status: "active" } : prev);
    await loadCampaigns();
  };

  // ── Tab navigation ────────────────────────────────────────────────────────

  const TABS: { key: Tab; label: string; icon: string }[] = [
    { key: "search", label: "Find Contacts", icon: "🔍" },
    { key: "contacts", label: "Contacts", icon: "👥" },
    { key: "lists", label: "Lists", icon: "📋" },
    { key: "campaigns", label: "Campaigns", icon: "📨" },
  ];

  const TAB_BTN = (t: typeof TABS[0]): React.CSSProperties => ({
    display: "flex", alignItems: "center", gap: 7,
    padding: "8px 16px", borderRadius: 20, fontSize: 13, fontWeight: 500,
    cursor: "pointer", transition: "all 0.12s",
    border: tab === t.key ? "1px solid rgba(96,165,250,0.35)" : "1px solid transparent",
    background: tab === t.key ? "rgba(96,165,250,0.12)" : "transparent",
    color: tab === t.key ? "#93c5fd" : "var(--fg-mute)",
  });

  return (
    <div style={{ width: "100%", maxWidth: 1200, margin: "0 auto", display: "flex", flexDirection: "column", gap: 20 }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>Outreach</h1>
          <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: "4px 0 0" }}>
            Find contacts, build lists, send personalized campaigns
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)} style={TAB_BTN(t)}>
              <span>{t.icon}</span>{t.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Tab: Find Contacts ──────────────────────────────────────────────── */}
      {tab === "search" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Audience input — primary entry point */}
          <div style={{ ...glass({ padding: "20px", display: "flex", flexDirection: "column", gap: 12 }) }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)", marginBottom: 4 }}>Who are you trying to reach?</div>
              <div style={{ fontSize: 12, color: "var(--fg-mute)" }}>Describe your target audience and we'll find verified contacts from our database</div>
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <input
                value={targetAudience}
                onChange={e => setTargetAudience(e.target.value)}
                onKeyDown={e => e.key === "Enter" && !findingContacts && findContacts()}
                placeholder='e.g. "restaurant owners in the US" or "SaaS startup CTOs" or "e-commerce store owners"'
                className="site-input"
                style={{ flex: 1, padding: "10px 14px", fontSize: 13 }}
              />
              <button
                onClick={findContacts}
                disabled={findingContacts || !targetAudience.trim()}
                className="site-btn site-btn-primary"
                style={{ padding: "0 24px", fontSize: 13, whiteSpace: "nowrap" }}
              >
                {findingContacts ? (
                  <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ width: 12, height: 12, border: "2px solid rgba(255,255,255,0.3)", borderTopColor: "#fff", borderRadius: "50%", animation: "spin 0.8s linear infinite", display: "inline-block" }} />
                    Finding contacts…
                  </span>
                ) : "Find Contacts →"}
              </button>
            </div>

            {findingContacts && (
              <p style={{ fontSize: 12, color: "var(--fg-mute)", margin: 0 }}>
                Searching our contact database — this takes ~30s
              </p>
            )}

            {findResult && (
              <div style={{
                padding: "10px 14px", borderRadius: 10,
                background: findResult.error ? "rgba(248,113,113,0.08)" : "rgba(74,222,128,0.08)",
                border: `1px solid ${findResult.error ? "rgba(248,113,113,0.2)" : "rgba(74,222,128,0.2)"}`,
                fontSize: 12,
              }}>
                {findResult.error ? (
                  <span style={{ color: "#f87171" }}>{findResult.error}</span>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <span style={{ color: "#4ade80", fontWeight: 600 }}>
                      Found {findResult.contacts_found} contacts with verified emails
                    </span>
                    <span style={{ color: "var(--fg-mute)" }}>
                      Searched {findResult.domains_searched?.length || 0} companies: {(findResult.domains_searched || []).slice(0, 6).join(", ")}{(findResult.domains_searched?.length || 0) > 6 ? "…" : ""}
                    </span>
                  </div>
                )}
              </div>
            )}

            {searchError && (
              <p style={{ fontSize: 12, color: "#f87171", margin: 0 }}>{searchError}</p>
            )}
          </div>

          {/* Filter + results — shown once contacts exist */}
          <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: 14, alignItems: "start" }}>
            <div style={{ ...glass({ padding: "14px", display: "flex", flexDirection: "column", gap: 12 }) }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Filter saved contacts</span>
              {[
                { label: "Job Title", value: searchTitles, set: setSearchTitles, placeholder: "CEO, CTO, Founder" },
                { label: "Location", value: searchLocations, set: setSearchLocations, placeholder: "United States" },
                { label: "Industry", value: searchIndustries, set: setSearchIndustries, placeholder: "SaaS, Fintech" },
              ].map(f => (
                <div key={f.label} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                  <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--fg-mute)" }}>{f.label}</span>
                  <input value={f.value} onChange={e => f.set(e.target.value)} placeholder={f.placeholder}
                    onKeyDown={e => e.key === "Enter" && runSearch(1)} className="site-input" style={{ padding: "6px 10px", fontSize: 12 }} />
                </div>
              ))}
              <CheckGroup label="Seniority" options={SENIORITY_OPTIONS} selected={selectedSeniorities} onChange={setSelectedSeniorities} />
              <CheckGroup label="Company Size" options={COMPANY_SIZE_OPTIONS} selected={selectedSizes} onChange={setSelectedSizes} />
              <button onClick={() => runSearch(1)} disabled={searching} className="site-btn site-btn-ghost"
                style={{ height: 34, fontSize: 12, width: "100%" }}>
                {searching ? "Filtering…" : "Filter →"}
              </button>
            </div>

          {/* Results */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {searchResults.length > 0 && (
              <>
                {/* Results header */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontSize: 13, color: "var(--fg-mute)" }}>
                      {selectedContacts.size > 0 ? `${selectedContacts.size} selected` : `${searchTotal.toLocaleString()} results`}
                    </span>
                    <button onClick={selectAll} style={{
                      fontSize: 11, color: "#60a5fa", background: "none", border: "none", cursor: "pointer", padding: 0,
                    }}>
                      {selectedContacts.size === searchResults.length ? "Deselect all" : "Select all"}
                    </button>
                  </div>
                  {selectedContacts.size > 0 && (
                    <div style={{ display: "flex", gap: 8 }}>
                      <button
                        onClick={() => saveSelected()}
                        className="site-btn site-btn-ghost"
                        style={{ fontSize: 12, padding: "0 14px", height: 32 }}
                      >
                        Save {selectedContacts.size} contacts
                      </button>
                      <button
                        onClick={() => {
                          const name = prompt("List name:");
                          if (name) saveSelected(name);
                        }}
                        className="site-btn site-btn-primary"
                        style={{ fontSize: 12, padding: "0 14px", height: 32 }}
                      >
                        Save to list →
                      </button>
                    </div>
                  )}
                </div>

                {/* Column headers */}
                <div style={{
                  display: "grid", gridTemplateColumns: "28px 1fr 1fr 120px 100px 80px",
                  gap: 12, padding: "6px 14px",
                  fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)",
                }}>
                  <div />
                  <div>Contact</div><div>Role</div><div>Industry</div><div>Location</div><div>Status</div>
                </div>

                {/* Rows */}
                <div style={{ ...glass({ padding: "8px" }), display: "flex", flexDirection: "column", gap: 2 }}>
                  {searchResults.map((c, i) => (
                    <ContactRow
                      key={c.apollo_id || c.email || i}
                      contact={c}
                      selected={selectedContacts.has(c.apollo_id || c.email)}
                      onSelect={toggleContact}
                    />
                  ))}
                </div>

                {/* Pagination */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                  <button
                    onClick={() => runSearch(searchPage - 1)}
                    disabled={searchPage <= 1 || searching}
                    className="site-btn site-btn-ghost"
                    style={{ fontSize: 12, padding: "0 14px", height: 32 }}
                  >← Prev</button>
                  <span style={{ fontSize: 12, color: "var(--fg-mute)" }}>Page {searchPage}</span>
                  <button
                    onClick={() => runSearch(searchPage + 1)}
                    disabled={searching || searchResults.length < 25}
                    className="site-btn site-btn-ghost"
                    style={{ fontSize: 12, padding: "0 14px", height: 32 }}
                  >Next →</button>
                </div>
              </>
            )}

            {searchResults.length === 0 && !searching && (
              <div style={{ ...glass({ padding: "60px 20px" }), textAlign: "center" }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>👆</div>
                <p style={{ fontSize: 14, color: "var(--fg-dim)", margin: "0 0 6px", fontWeight: 500 }}>
                  Describe your target audience above
                </p>
                <p style={{ fontSize: 12, color: "var(--fg-mute)", margin: 0 }}>
                  We'll search our contact database and return verified emails for that audience
                </p>
              </div>
            )}

            {searching && (
              <div style={{ ...glass({ padding: "60px 20px" }), textAlign: "center" }}>
                <div style={{ width: 28, height: 28, border: "3px solid rgba(255,255,255,0.1)", borderTopColor: "#60a5fa", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 12px" }} />
                <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: 0 }}>Filtering…</p>
              </div>
            )}
          </div>
          {/* end inner results col */}
          </div>
          {/* end filter+results grid */}
        </div>
        /* end search tab */
      )}

      {/* ── Tab: Contacts ───────────────────────────────────────────────────── */}
      {tab === "contacts" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {/* Status filter */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {["", "new", "contacted", "replied", "meeting", "won", "lost"].map(s => (
              <button key={s} onClick={() => { setContactStatusFilter(s); loadContacts(); }} style={{
                ...PILL,
                background: contactStatusFilter === s ? "rgba(96,165,250,0.15)" : "rgba(255,255,255,0.05)",
                border: `1px solid ${contactStatusFilter === s ? "rgba(96,165,250,0.3)" : "rgba(255,255,255,0.1)"}`,
                color: contactStatusFilter === s ? "#93c5fd" : "var(--fg-mute)",
                cursor: "pointer",
              }}>{s || "All"}</button>
            ))}
          </div>

          {contactsLoading ? (
            <div style={{ textAlign: "center", padding: 40, color: "var(--fg-mute)", fontSize: 13 }}>Loading…</div>
          ) : savedContacts.length === 0 ? (
            <div style={{ ...glass({ padding: "60px 20px" }), textAlign: "center" }}>
              <p style={{ fontSize: 14, color: "var(--fg-mute)", margin: 0 }}>No contacts yet. Go to Find Contacts, describe your target audience, and we'll pull verified emails.</p>
            </div>
          ) : (
            <>
              <div style={{
                display: "grid", gridTemplateColumns: "28px 1fr 1fr 120px 100px 80px",
                gap: 12, padding: "6px 14px",
                fontSize: 10, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--fg-mute)",
              }}>
                <div /><div>Contact</div><div>Role</div><div>Industry</div><div>Location</div><div>Status</div>
              </div>
              <div style={{ ...glass({ padding: "8px" }), display: "flex", flexDirection: "column", gap: 2 }}>
                {savedContacts.map((c, i) => (
                  <ContactRow key={c.id || i} contact={c} selected={false} onSelect={() => {}} />
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Tab: Lists ──────────────────────────────────────────────────────── */}
      {tab === "lists" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={newListName}
              onChange={e => setNewListName(e.target.value)}
              placeholder="New list name…"
              className="site-input"
              style={{ padding: "8px 12px", fontSize: 13, flex: 1, maxWidth: 300 }}
              onKeyDown={e => e.key === "Enter" && newListName.trim() && (setCreatingList(true), apiFetch(`${BASE}/outreach/lists/${founderId}`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: newListName }),
              }).then(() => { setNewListName(""); loadLists(); }).finally(() => setCreatingList(false)))}
            />
            <button
              onClick={() => {
                if (!newListName.trim()) return;
                setCreatingList(true);
                apiFetch(`${BASE}/outreach/lists/${founderId}`, {
                  method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ name: newListName }),
                }).then(() => { setNewListName(""); loadLists(); }).finally(() => setCreatingList(false));
              }}
              disabled={creatingList || !newListName.trim()}
              className="site-btn site-btn-primary"
              style={{ fontSize: 13, padding: "0 20px" }}
            >
              {creatingList ? "…" : "Create List"}
            </button>
          </div>

          {lists.length === 0 ? (
            <div style={{ ...glass({ padding: "60px 20px" }), textAlign: "center" }}>
              <p style={{ fontSize: 14, color: "var(--fg-mute)", margin: 0 }}>No lists yet. Save contacts from the Search tab to create one.</p>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 10 }}>
              {lists.map(l => (
                <div key={l.id} style={{ ...glass({ padding: "14px 16px" }) }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--fg)" }}>{l.name}</div>
                  {l.description && <div style={{ fontSize: 12, color: "var(--fg-mute)", marginTop: 3 }}>{l.description}</div>}
                  <div style={{ marginTop: 8, fontSize: 11, color: "var(--fg-mute)" }}>
                    {l.contact_count} contact{l.contact_count !== 1 ? "s" : ""}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Tab: Campaigns ─────────────────────────────────────────────────── */}
      {tab === "campaigns" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button onClick={() => setShowNewCampaign(true)} className="site-btn site-btn-primary" style={{ fontSize: 13, padding: "0 20px" }}>
              + New Campaign
            </button>
          </div>

          {campaignsLoading ? (
            <div style={{ textAlign: "center", padding: 40, color: "var(--fg-mute)" }}>Loading…</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 12 }}>
              {campaigns.map(c => (
                <CampaignCard key={c.id} campaign={c} stats={campaignStats[c.id]} onClick={() => openCampaign(c)} />
              ))}
              {campaigns.length === 0 && (
                <div style={{ ...glass({ padding: "60px 20px" }), textAlign: "center", gridColumn: "1/-1" }}>
                  <p style={{ fontSize: 14, color: "var(--fg-mute)", margin: 0 }}>No campaigns yet. Create one to start sending.</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── New campaign modal ───────────────────────────────────────────────── */}
      {showNewCampaign && (
        <div style={{ position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,0.7)", backdropFilter: "blur(12px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
          <div style={{ ...glass({ padding: "24px", width: "100%", maxWidth: 480, display: "flex", flexDirection: "column", gap: 14 }) }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 16, fontWeight: 600, color: "var(--fg)" }}>New Campaign</span>
              <button onClick={() => setShowNewCampaign(false)} style={{ background: "none", border: "none", color: "var(--fg-mute)", cursor: "pointer", fontSize: 18 }}>✕</button>
            </div>

            {[
              { label: "Campaign Name", key: "name", placeholder: "Q1 Outreach" },
              { label: "From Name", key: "from_name", placeholder: "Alex from Astra" },
              { label: "From Email", key: "from_email", placeholder: "alex@yourcompany.com" },
              { label: "Product Name", key: "product_name", placeholder: "Astra" },
              { label: "Value Proposition", key: "value_prop", placeholder: "Helps founders build startups 10x faster" },
            ].map(f => (
              <div key={f.key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <label style={{ fontSize: 11, color: "var(--fg-mute)", textTransform: "uppercase", letterSpacing: "0.08em" }}>{f.label}</label>
                <input
                  value={(newCampaign as Record<string, string | number>)[f.key] as string}
                  onChange={e => setNewCampaign(p => ({ ...p, [f.key]: e.target.value }))}
                  placeholder={f.placeholder}
                  className="site-input"
                  style={{ padding: "8px 12px", fontSize: 13 }}
                />
              </div>
            ))}

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button onClick={() => setShowNewCampaign(false)} className="site-btn site-btn-ghost" style={{ fontSize: 13, padding: "0 16px" }}>Cancel</button>
              <button onClick={createCampaign} className="site-btn site-btn-primary" style={{ fontSize: 13, padding: "0 20px" }}>Create →</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Campaign detail modal ─────────────────────────────────────────────── */}
      {selectedCampaign && (
        <div style={{ position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,0.7)", backdropFilter: "blur(12px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
          <div style={{ ...glass({ padding: "24px", width: "100%", maxWidth: 640, maxHeight: "80vh", overflow: "auto", display: "flex", flexDirection: "column", gap: 16 }) }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontSize: 18, fontWeight: 600, color: "var(--fg)" }}>{selectedCampaign.name}</div>
                <div style={{ fontSize: 12, color: "var(--fg-mute)", marginTop: 3 }}>
                  {selectedCampaign.from_name} · {selectedCampaign.from_email}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{
                  ...PILL,
                  background: CAMPAIGN_STATUS_COLORS[selectedCampaign.status] || "rgba(255,255,255,0.1)",
                  color: "var(--fg-dim)",
                }}>{selectedCampaign.status}</span>
                <button onClick={() => setSelectedCampaign(null)} style={{ background: "none", border: "none", color: "var(--fg-mute)", cursor: "pointer", fontSize: 18 }}>✕</button>
              </div>
            </div>

            {/* Stats */}
            {campaignStats[selectedCampaign.id] && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8 }}>
                <StatBadge label="Sent" value={campaignStats[selectedCampaign.id].sent} />
                <StatBadge label="Open Rate" value={`${campaignStats[selectedCampaign.id].open_rate}%`} color="#60a5fa" />
                <StatBadge label="Click Rate" value={`${campaignStats[selectedCampaign.id].click_rate}%`} color="#a78bfa" />
                <StatBadge label="Reply Rate" value={`${campaignStats[selectedCampaign.id].reply_rate}%`} color="#4ade80" />
              </div>
            )}

            {/* Steps */}
            <div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)" }}>Email Sequence ({selectedCampaign.steps?.length || 0} steps)</span>
                <button
                  onClick={() => generateSteps(selectedCampaign.id)}
                  disabled={generatingSteps}
                  className="site-btn site-btn-ghost"
                  style={{ fontSize: 11, padding: "0 12px", height: 28 }}
                >
                  {generatingSteps ? "Generating…" : selectedCampaign.steps?.length ? "Regenerate" : "Generate with AI →"}
                </button>
              </div>
              {editingSteps.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {editingSteps.map((step, i) => (
                    <div key={i} style={{ ...glass({ padding: "12px 14px", borderRadius: 12 }), display: "flex", flexDirection: "column", gap: 8 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ ...PILL, background: "rgba(96,165,250,0.15)", color: "#93c5fd", flexShrink: 0 }}>Day {step.send_day}</span>
                        <input
                          value={step.subject}
                          onChange={e => setEditingSteps(prev => prev.map((s, idx) => idx === i ? { ...s, subject: e.target.value } : s))}
                          placeholder="Subject line…"
                          className="site-input"
                          style={{ flex: 1, padding: "5px 10px", fontSize: 12, fontWeight: 500 }}
                        />
                      </div>
                      <textarea
                        value={step.body}
                        onChange={e => setEditingSteps(prev => prev.map((s, idx) => idx === i ? { ...s, body: e.target.value } : s))}
                        placeholder="Email body… Use {{first_name}}, {{company_name}}, {{title}}"
                        className="site-input"
                        rows={6}
                        style={{ fontSize: 11, lineHeight: 1.6, resize: "vertical", padding: "8px 10px", fontFamily: "var(--font-mono)" }}
                      />
                    </div>
                  ))}
                  <button
                    onClick={saveSteps}
                    disabled={savingSteps}
                    className="site-btn site-btn-ghost"
                    style={{ fontSize: 12, height: 32, alignSelf: "flex-end", padding: "0 16px" }}
                  >
                    {savingSteps ? "Saving…" : "Save edits"}
                  </button>
                </div>
              ) : (
                <div style={{ ...glass({ padding: "20px", textAlign: "center", borderRadius: 12 }) }}>
                  <p style={{ margin: 0, fontSize: 12, color: "var(--fg-mute)" }}>No steps yet. Generate an AI sequence above.</p>
                </div>
              )}
            </div>

            {/* Batch send result */}
            {batchResult && (
              <div style={{ padding: "8px 12px", borderRadius: 10, background: batchResult.failed > 0 ? "rgba(251,191,36,0.08)" : "rgba(74,222,128,0.08)", border: `1px solid ${batchResult.failed > 0 ? "rgba(251,191,36,0.2)" : "rgba(74,222,128,0.2)"}`, fontSize: 12 }}>
                <span style={{ color: "#4ade80" }}>{batchResult.sent} sent via Gmail</span>
                {batchResult.failed > 0 && <span style={{ color: "#fbbf24", marginLeft: 10 }}>{batchResult.failed} failed — check Gmail is connected</span>}
              </div>
            )}

            {/* Actions */}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
              {selectedCampaign.status === "draft" && editingSteps.length > 0 && (
                <button
                  onClick={async () => {
                    await launchCampaign(selectedCampaign.id);
                    // Fire first batch immediately after launch
                    await sendBatch();
                  }}
                  className="site-btn site-btn-primary"
                  style={{ fontSize: 13, padding: "0 20px" }}
                >
                  Launch &amp; Send →
                </button>
              )}
              {selectedCampaign.status === "active" && (
                <>
                  <button
                    onClick={sendBatch}
                    disabled={sendingBatch}
                    className="site-btn site-btn-primary"
                    style={{ fontSize: 13, padding: "0 20px" }}
                  >
                    {sendingBatch ? "Sending…" : "Send Next Batch →"}
                  </button>
                  <button
                    onClick={async () => {
                      await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${selectedCampaign.id}`, {
                        method: "PATCH", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ status: "paused" }),
                      });
                      setSelectedCampaign(null);
                      loadCampaigns();
                    }}
                    className="site-btn"
                    style={{ fontSize: 13, padding: "0 20px", color: "#fbbf24", borderColor: "rgba(251,191,36,0.3)", background: "rgba(251,191,36,0.08)" }}
                  >
                    Pause
                  </button>
                </>
              )}
              {selectedCampaign.status === "paused" && (
                <button
                  onClick={async () => {
                    await apiFetch(`${BASE}/outreach/campaigns/${founderId}/${selectedCampaign.id}`, {
                      method: "PATCH", headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ status: "active" }),
                    });
                    await loadCampaigns();
                    await sendBatch();
                  }}
                  className="site-btn site-btn-primary"
                  style={{ fontSize: 13, padding: "0 20px" }}
                >
                  Resume &amp; Send →
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
}
