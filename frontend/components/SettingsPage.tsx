"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useDevUser } from "@/lib/use-dev-user";
import ThemeToggle from "@/components/ThemeToggle";
import {
  createOrganizationBillingPortal,
  createOrganizationCheckout,
  createOrganizationInvite,
  getDeployEvidence,
  getLaunchReadiness,
  getOrganization,
  getOrganizationBilling,
  getPlatformStatus,
  getProductionLaunchProof,
  getProductionRequirements,
  getProductionVerificationReports,
  productionVerificationBundleUrl,
  productionVerificationMarkdownUrl,
  runProductionLaunch,
  verifyProductionVerificationManifest,
  type BillingConfigStatus,
  type DeployEvidenceReport,
  type LaunchReadiness,
  type OrganizationAccount,
  type PlatformStatus,
  type ProductionLaunchProofResponse,
  type ProductionRequirements,
  type ProductionVerificationManifestVerification,
  type ProductionVerificationReport,
} from "@/lib/api";

// ── Design tokens ─────────────────────────────────────────────────────────────
const c = {
  bg: "#FFFFFF",
  surface: "#F8F9FA",
  border: "#E5E7EB",
  borderStrong: "#D1D5DB",
  text: "#111827",
  textSecondary: "#374151",
  textMuted: "#9CA3AF",
  grey: "#6B7280",
  blue: "#002EFF",
  blueHover: "#0024CC",
  blueTint: "#E8ECFF",
  green: "#16a34a",
  greenTint: "#DCFCE7",
  greenBorder: "#BBF7D0",
  amber: "#d97706",
  amberTint: "#FEF9C3",
  amberBorder: "#FDE68A",
  red: "#dc2626",
  redTint: "#FEF2F2",
  redBorder: "#FECACA",
};

function inputStyle(focused = false): React.CSSProperties {
  return {
    width: "100%",
    minHeight: 42,
    borderRadius: 8,
    border: `1px solid ${focused ? c.blue : c.border}`,
    background: c.bg,
    color: c.text,
    padding: "0 14px",
    outline: "none",
    fontSize: 13,
    boxSizing: "border-box" as const,
    fontFamily: "var(--font-geist-sans)",
  };
}

// ── Section & Row ─────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column",
      borderRadius: 14, overflow: "hidden",
      border: `1px solid ${c.border}`,
      background: c.bg,
      boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
    }}>
      <div style={{ padding: "14px 20px", borderBottom: `1px solid ${c.border}`, background: c.surface }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: c.text }}>{title}</span>
      </div>
      {children}
    </div>
  );
}

function Row({ label, desc, action }: { label: string; desc?: string; action: React.ReactNode }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      gap: 20, padding: "14px 20px", borderBottom: `1px solid ${c.border}`,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: 0, fontSize: 13, color: c.text, fontWeight: 500 }}>{label}</p>
        {desc && <p style={{ margin: "2px 0 0", fontSize: 12, color: c.grey, lineHeight: 1.5 }}>{desc}</p>}
      </div>
      {action != null && <div style={{ flexShrink: 0 }}>{action}</div>}
    </div>
  );
}

// ── Badge ────────────────────────────────────────────────────────────────────

function Badge({ children, color = "grey" }: { children: React.ReactNode; color?: "grey" | "green" | "amber" | "blue" | "red" }) {
  const map = {
    grey: { bg: "#F3F4F6", text: c.grey, border: c.border },
    green: { bg: c.greenTint, text: c.green, border: c.greenBorder },
    amber: { bg: c.amberTint, text: c.amber, border: c.amberBorder },
    blue: { bg: c.blueTint, text: c.blue, border: "#BFDBFE" },
    red: { bg: c.redTint, text: c.red, border: c.redBorder },
  }[color];
  return (
    <span style={{
      fontSize: 11, padding: "4px 10px", borderRadius: 999, fontWeight: 500, whiteSpace: "nowrap",
      background: map.bg, color: map.text, border: `1px solid ${map.border}`,
    }}>
      {children}
    </span>
  );
}

// ── Mini card ─────────────────────────────────────────────────────────────────

function MiniCard({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      borderRadius: 10, border: `1px solid ${c.border}`,
      background: c.surface, padding: "10px 12px",
      ...style,
    }}>
      {children}
    </div>
  );
}

// ─── Team types ───────────────────────────────────────────────────────────────
interface TeamMember {
  uid: string;
  email?: string;
  role: string;
  status?: string;
}

interface Team {
  id: string;
  name: string;
  founder_id: string;
  members: TeamMember[];
}

// ─── TeamSection ──────────────────────────────────────────────────────────────
function TeamSection({ founderId, org }: { founderId: string; org: OrganizationAccount | null }) {
  const [team, setTeam] = useState<Team | null>(null);
  const [loading, setLoading] = useState(true);
  const [createName, setCreateName] = useState("");
  const [creating, setCreating] = useState(false);
  const [showCreateInput, setShowCreateInput] = useState(false);
  const [createError, setCreateError] = useState("");
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"viewer" | "operator" | "admin">("viewer");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [inviteError, setInviteError] = useState("");
  const [inviteUrl, setInviteUrl] = useState("");
  const [removingUid, setRemovingUid] = useState<string | null>(null);

  const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  useEffect(() => {
    if (!founderId) return;
    setLoading(true);
    fetch(`${BASE}/teams/me?founder_id=${encodeURIComponent(founderId)}`)
      .then((res) => res.ok ? res.json() : null)
      .then((data) => setTeam(data ?? null))
      .catch(() => setTeam(null))
      .finally(() => setLoading(false));
  }, [founderId, BASE]);

  const handleCreate = async () => {
    if (!createName.trim()) return;
    setCreating(true);
    setCreateError("");
    try {
      const res = await fetch(`${BASE}/teams`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: createName.trim(), founder_id: founderId }),
      });
      if (!res.ok) throw new Error(await res.text());
      const created: Team = await res.json();
      setTeam(created);
      setShowCreateInput(false);
      setCreateName("");
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create team.");
    } finally {
      setCreating(false);
    }
  };

  const handleInvite = async () => {
      if (!team && !org) return;
      setInviteBusy(true);
      setInviteError("");
      try {
        const data = await createOrganizationInvite(org?.org_id || founderId, {
          email: inviteEmail.trim() || undefined,
          role: inviteRole,
        });
        const url: string = data.invite_url ?? "";
        setInviteUrl(url);
        if (url) await navigator.clipboard.writeText(url);
      setInviteEmail("");
      setShowInviteModal(false);
    } catch (err) {
      setInviteError(err instanceof Error ? err.message : "Failed to generate invite.");
    } finally {
      setInviteBusy(false);
    }
  };

  const handleRemove = async (uid: string) => {
    if (!team) return;
    setRemovingUid(uid);
    try {
      await fetch(`${BASE}/teams/${team.id}/members/${uid}?founder_id=${encodeURIComponent(founderId)}`, {
        method: "DELETE",
      });
      setTeam((prev) => prev ? { ...prev, members: prev.members.filter((m) => m.uid !== uid) } : prev);
    } catch {
      // silently ignore remove errors
    } finally {
      setRemovingUid(null);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: "14px 20px" }}>
        <span style={{ fontSize: 13, color: c.textMuted }}>Loading team…</span>
      </div>
    );
  }

  if (!team) {
    return (
      <div style={{ padding: "14px 20px", display: "grid", gap: 12 }}>
        {showCreateInput ? (
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <input
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder="Team name…"
              style={{ flex: 1, minHeight: 38, borderRadius: 8, border: `1px solid ${c.border}`, background: c.bg, color: c.text, padding: "0 14px", outline: "none", fontSize: 13 }}
              onFocus={e => (e.target.style.borderColor = c.blue)}
              onBlur={e => (e.target.style.borderColor = c.border)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            />
            <button
              onClick={handleCreate}
              disabled={creating || !createName.trim()}
              style={{
                fontSize: 13, padding: "0 16px", minHeight: 38, borderRadius: 8,
                background: c.blue, color: "#FFFFFF", border: "none",
                cursor: creating || !createName.trim() ? "not-allowed" : "pointer",
                opacity: creating ? 0.6 : 1, fontWeight: 500,
              }}
            >
              {creating ? "Creating…" : "Create"}
            </button>
            <button
              onClick={() => { setShowCreateInput(false); setCreateName(""); setCreateError(""); }}
              style={{
                fontSize: 13, padding: "0 14px", minHeight: 38, borderRadius: 8,
                background: c.bg, color: c.textSecondary, border: `1px solid ${c.border}`, cursor: "pointer",
              }}
            >
              Cancel
            </button>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <p style={{ margin: 0, fontSize: 13, color: c.grey }}>You are not in a team yet.</p>
            <button
              onClick={() => setShowCreateInput(true)}
              style={{
                fontSize: 13, padding: "0 16px", minHeight: 36, borderRadius: 8,
                background: c.blue, color: "#FFFFFF", border: "none", cursor: "pointer", fontWeight: 500,
              }}
            >
              Create Team
            </button>
          </div>
        )}
        {createError && (
          <span style={{ fontSize: 12, color: c.red }}>{createError}</span>
        )}
      </div>
    );
  }

  const isOwner = team.founder_id === founderId;

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {/* Team header row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "14px 20px", borderBottom: `1px solid ${c.border}` }}>
        <div>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 600, color: c.text }}>{team.name}</p>
          <p style={{ margin: "2px 0 0", fontSize: 12, color: c.grey }}>{team.members?.length ?? 0} member{(team.members?.length ?? 0) !== 1 ? "s" : ""}</p>
        </div>
        {isOwner && (
          <button
            onClick={() => { setShowInviteModal(true); setInviteError(""); }}
            style={{
              fontSize: 13, padding: "0 16px", minHeight: 36, borderRadius: 8,
              background: c.blue, color: "#FFFFFF", border: "none", cursor: "pointer", fontWeight: 500,
            }}
          >
            Invite →
          </button>
        )}
      </div>

      {/* Members list */}
      {(team.members ?? []).map((member, i) => (
        <div key={member.uid} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "12px 20px", borderBottom: `1px solid ${c.border}`, background: i % 2 === 1 ? c.surface : c.bg }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
            <div style={{
              width: 32, height: 32, borderRadius: "50%",
              background: c.blueTint, border: `1px solid #BFDBFE`,
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            }}>
              <span style={{ fontSize: 13, color: c.blue, fontWeight: 600 }}>{(member.email ?? member.uid).charAt(0).toUpperCase()}</span>
            </div>
            <div style={{ minWidth: 0 }}>
              <p style={{ margin: 0, fontSize: 13, color: c.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{member.email ?? member.uid}</p>
              <p style={{ margin: 0, fontSize: 11, color: c.textMuted }}>{member.role}{member.status && member.status !== "active" ? ` · ${member.status}` : ""}</p>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            <Badge color={member.uid === team.founder_id ? "green" : "grey"}>
              {member.uid === team.founder_id ? "owner" : member.role}
            </Badge>
            {isOwner && member.uid !== founderId && (
              <button
                onClick={() => handleRemove(member.uid)}
                disabled={removingUid === member.uid}
                style={{
                  fontSize: 12, padding: "4px 10px", minHeight: 28, borderRadius: 6,
                  color: c.red, background: c.redTint, border: `1px solid ${c.redBorder}`,
                  cursor: removingUid === member.uid ? "not-allowed" : "pointer",
                  opacity: removingUid === member.uid ? 0.5 : 1,
                }}
              >
                {removingUid === member.uid ? "…" : "Remove"}
              </button>
            )}
          </div>
        </div>
      ))}

      {/* Invite modal */}
      {showInviteModal && (
        <div
          className="astra-modal-backdrop"
          onClick={(e) => { if (e.target === e.currentTarget) setShowInviteModal(false); }}
        >
          <div className="astra-modal-shell" style={{ maxWidth: 500 }} onClick={(e) => e.stopPropagation()}>
            <div className="astra-modal-panel">
              <div className="astra-modal-header">
                <div className="astra-modal-header-row">
                  <div>
                    <div className="astra-modal-eyebrow">team access</div>
                    <h2 className="astra-modal-title" style={{ fontSize: 24 }}>Invite to {org?.name || team?.name || "Company"}</h2>
                    <p className="astra-modal-sub">Bring someone into the workspace with the right role. Generate a shareable invite link or send it to a teammate.</p>
                  </div>
                  <button
                    onClick={() => { setShowInviteModal(false); setInviteEmail(""); setInviteError(""); }}
                    className="astra-modal-close"
                    aria-label="Close invite modal"
                  >
                    ×
                  </button>
                </div>
              </div>
              <div className="astra-modal-body">
                <div className="astra-modal-card" style={{ padding: 16, display: "grid", gap: 18 }}>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: c.textMuted, fontWeight: 500 }}>Email (optional)</span>
                    <input
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                      placeholder="teammate@example.com"
                      type="email"
                      style={inputStyle()}
                      onFocus={e => (e.target.style.borderColor = c.blue)}
                      onBlur={e => (e.target.style.borderColor = c.border)}
                      onKeyDown={(e) => e.key === "Enter" && handleInvite()}
                    />
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: c.textMuted, fontWeight: 500 }}>Role</span>
                    <select
                      value={inviteRole}
                      onChange={(e) => setInviteRole(e.target.value as typeof inviteRole)}
                      style={inputStyle()}
                    >
                      <option value="viewer">Viewer</option>
                      <option value="operator">Operator</option>
                      <option value="admin">Admin</option>
                    </select>
                  </label>
                </div>
                {inviteUrl && (
                  <MiniCard>
                    <div style={{ fontSize: 11, color: c.grey, marginBottom: 4 }}>Copied invite link</div>
                    <div style={{ fontSize: 12, color: c.textSecondary, wordBreak: "break-all" }}>{inviteUrl}</div>
                  </MiniCard>
                )}
                {inviteError && (
                  <span style={{ fontSize: 12, color: c.red }}>{inviteError}</span>
                )}
                <div className="astra-modal-actions">
                  <button
                    onClick={() => { setShowInviteModal(false); setInviteEmail(""); setInviteError(""); }}
                    style={{
                      fontSize: 13, padding: "0 16px", minHeight: 38, borderRadius: 8,
                      background: c.bg, color: c.textSecondary, border: `1px solid ${c.border}`, cursor: "pointer",
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleInvite}
                    disabled={inviteBusy}
                    style={{
                      fontSize: 13, padding: "0 18px", minHeight: 38, borderRadius: 8,
                      background: c.blue, color: "#FFFFFF", border: "none",
                      cursor: inviteBusy ? "not-allowed" : "pointer", fontWeight: 500,
                      opacity: inviteBusy ? 0.6 : 1,
                    }}
                  >
                    {inviteBusy ? "Generating…" : "Copy invite link"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function statusColor(status: string, ok?: boolean): "green" | "amber" | "red" {
  if (ok || status === "code_ready" || status === "production_verified") return "green";
  if (status === "needs_live_proof") return "amber";
  return "red";
}

const statusHexColor = (status: string, ok?: boolean) => {
  const col = statusColor(status, ok);
  return col === "green" ? c.green : col === "amber" ? c.amber : c.red;
};

export default function SettingsPage() {
  const { userId } = useDevUser();
  const founderId = userId === "anon" ? "founder_001" : userId;
  const [platform, setPlatform] = useState<PlatformStatus | null>(null);
  const [org, setOrg] = useState<OrganizationAccount | null>(null);
  const [baseUrl, setBaseUrl] = useState("https://api.astracreates.com");
  const [stackId, setStackId] = useState("idea_to_revenue");
  const [liveConnectors, setLiveConnectors] = useState(true);
  const [deployEvidence, setDeployEvidence] = useState<DeployEvidenceReport | null>(null);
  const [requirements, setRequirements] = useState<ProductionRequirements | null>(null);
  const [launchReadiness, setLaunchReadiness] = useState<LaunchReadiness | null>(null);
  const [latestLaunchProof, setLatestLaunchProof] = useState<ProductionLaunchProofResponse | null>(null);
  const [latestVerification, setLatestVerification] = useState<ProductionVerificationReport | null>(null);
  const [manifestVerification, setManifestVerification] = useState<ProductionVerificationManifestVerification | null>(null);
  const [verificationBusy, setVerificationBusy] = useState(false);
  const [manifestBusy, setManifestBusy] = useState(false);
  const [verificationError, setVerificationError] = useState("");
  const [backendStatus, setBackendStatus] = useState<"checking" | "online" | "offline">("checking");
  const [backendLatency, setBackendLatency] = useState<number | null>(null);
  const [billingConfig, setBillingConfig] = useState<BillingConfigStatus | null>(null);
  const [billingBusy, setBillingBusy] = useState(false);
  const [billingError, setBillingError] = useState("");

  useEffect(() => {
    const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    async function ping() {
      const t0 = Date.now();
      try {
        const res = await fetch(`${API}/health`, { signal: AbortSignal.timeout(5000) });
        if (res.ok) { setBackendStatus("online"); setBackendLatency(Date.now() - t0); }
        else setBackendStatus("offline");
      } catch { setBackendStatus("offline"); setBackendLatency(null); }
    }
    ping();
    const id = setInterval(ping, 30_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      getPlatformStatus(),
      getOrganization(founderId, founderId),
      getProductionVerificationReports(3),
      getDeployEvidence(founderId, stackId, baseUrl, false, true),
      getProductionRequirements(founderId, stackId, baseUrl),
      verifyProductionVerificationManifest("latest"),
      getLaunchReadiness(founderId, stackId, baseUrl, "latest"),
      getProductionLaunchProof("latest"),
      getOrganizationBilling(founderId),
    ]).then(([platformResult, orgResult, verificationResult, evidenceResult, requirementsResult, manifestResult, readinessResult, launchProofResult, billingResult]) => {
      if (cancelled) return;
      if (platformResult.status === "fulfilled") setPlatform(platformResult.value);
      if (orgResult.status === "fulfilled") setOrg(orgResult.value);
      if (verificationResult.status === "fulfilled") setLatestVerification(verificationResult.value.latest);
      if (evidenceResult.status === "fulfilled") setDeployEvidence(evidenceResult.value);
      if (requirementsResult.status === "fulfilled") setRequirements(requirementsResult.value);
      if (manifestResult.status === "fulfilled") setManifestVerification(manifestResult.value);
      if (readinessResult.status === "fulfilled") setLaunchReadiness(readinessResult.value);
      if (launchProofResult.status === "fulfilled") setLatestLaunchProof(launchProofResult.value);
      if (billingResult.status === "fulfilled") { setOrg(billingResult.value.org); setBillingConfig(billingResult.value.billing); }
    });
    return () => { cancelled = true; };
  }, [founderId, stackId, baseUrl]);

  const runFinalVerification = async () => {
    setVerificationBusy(true);
    setVerificationError("");
    try {
      const result = await runProductionLaunch({
        founder_id: founderId,
        base_url: baseUrl,
        stack_id: stackId,
        live_connectors: liveConnectors,
      });
      const report = result.verification;
      setLatestVerification(report);
      setDeployEvidence(report.deploy_evidence);
      const [updatedRequirements] = await Promise.all([
        getProductionRequirements(founderId, stackId, baseUrl),
      ]);
      setRequirements(updatedRequirements);
      setManifestVerification(result.manifest);
      setLaunchReadiness(result.launch_readiness);
      setLatestLaunchProof({ ok: true, found: true, proof: result as ProductionLaunchProofResponse["proof"] });
    } catch (error) {
      setVerificationError(error instanceof Error ? error.message : "Production launch proof failed.");
    } finally {
      setVerificationBusy(false);
    }
  };

  const verifyLatestManifest = async () => {
    setManifestBusy(true);
    setVerificationError("");
    try {
      const reportId = latestVerification?.id || "latest";
      const verified = await verifyProductionVerificationManifest(reportId);
      setManifestVerification(verified);
      const updatedReadiness = await getLaunchReadiness(founderId, stackId, baseUrl, reportId);
      setLaunchReadiness(updatedReadiness);
    } catch (error) {
      setVerificationError(error instanceof Error ? error.message : "Manifest verification failed.");
    } finally {
      setManifestBusy(false);
    }
  };

  return (
    <div style={{ width: "100%", maxWidth: 920, margin: "0 auto", display: "flex", flexDirection: "column", gap: 24, fontFamily: "var(--font-geist-sans)" }}>

      {/* Page header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Link href="/" style={{
            fontSize: 13, padding: "6px 14px", borderRadius: 8,
            background: c.bg, color: c.textSecondary,
            border: `1px solid ${c.border}`, textDecoration: "none", fontWeight: 500,
          }}>
            ← Back
          </Link>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: c.text, letterSpacing: "-0.02em" }}>Settings</h1>
            <p style={{ fontSize: 13, color: c.grey, margin: "3px 0 0" }}>Manage your account and preferences</p>
          </div>
        </div>
        <ThemeToggle />
      </div>

      {/* Account */}
      <Section title="Account">
        <Row
          label="Profile"
          desc={`Dev User (${founderId.slice(0, 16)})`}
          action={null}
        />
        <Row
          label="Plan"
          desc={org ? `${org.entitlements.remaining_runs}/${org.entitlements.monthly_runs} runs remaining · ${org.entitlements.remaining_team_seats} seats open` : "Developer workspace during beta"}
          action={<Badge color="blue">{org?.entitlements.name ?? "Beta"}</Badge>}
        />
        <Row
          label="Team access"
          desc={org ? `${Object.values(org.members).filter(member => member.status === "active").length} active member(s) · owner ${org.owner_id}` : "Team roles load from the organization control plane"}
          action={<Badge>Roles</Badge>}
        />
      </Section>

      {/* Integrations */}
      <Section title="Integrations">
        <Row
          label="GitHub · Vercel · Supabase · Composio"
          desc="Connect accounts for full agent capabilities"
          action={
            <Link
              href="/integrations"
              style={{
                fontSize: 13, padding: "6px 14px", borderRadius: 8,
                background: c.bg, color: c.textSecondary,
                border: `1px solid ${c.border}`, textDecoration: "none", fontWeight: 500,
                display: "inline-block", whiteSpace: "nowrap",
              }}
            >
              Manage →
            </Link>
          }
        />
        <Row
          label="Stripe"
          desc="Connect payment context for launch and revenue work"
          action={<Badge>Managed in integrations</Badge>}
        />
      </Section>

      {/* Onboarding */}
      <Section title="Onboarding">
        <Row
          label="Restart onboarding"
          desc="Re-run the setup wizard to change your stack or reconnect integrations"
          action={
            <button
              onClick={() => { localStorage.removeItem("astra_onboarding_done"); window.location.href = "/onboarding"; }}
              style={{
                fontSize: 13, padding: "6px 14px", borderRadius: 8,
                background: c.bg, color: c.textSecondary, border: `1px solid ${c.border}`, cursor: "pointer",
              }}
            >
              Restart →
            </button>
          }
        />
        <Row
          label="Retake workspace tour"
          desc="Replay the tooltip tour that explains each part of the workspace"
          action={
            <button
              onClick={() => { localStorage.setItem("astra_show_tour", "1"); window.location.href = "/"; }}
              style={{
                fontSize: 13, padding: "6px 14px", borderRadius: 8,
                background: c.bg, color: c.textSecondary, border: `1px solid ${c.border}`, cursor: "pointer",
              }}
            >
              Take tour →
            </button>
          }
        />
      </Section>

      {/* Notifications */}
      <Section title="Notifications">
        <Row
          label="Browser notifications"
          desc="Get notified when a goal completes"
          action={
            <button
              onClick={() => Notification.requestPermission()}
              style={{
                fontSize: 13, padding: "6px 14px", borderRadius: 8,
                background: c.blue, color: "#FFFFFF", border: "none", cursor: "pointer", fontWeight: 500,
              }}
            >
              Enable
            </button>
          }
        />
      </Section>

      {/* Platform */}
      <Section title="Platform">
        <Row
          label="Backend"
          desc={backendStatus === "checking" ? "Pinging server…" : backendStatus === "online" ? `Reachable · ${backendLatency}ms` : "Cannot reach server"}
          action={
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{
                width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                background: backendStatus === "online" ? c.green : backendStatus === "offline" ? c.red : c.amber,
                boxShadow: backendStatus === "online" ? `0 0 6px ${c.green}` : backendStatus === "offline" ? `0 0 6px ${c.red}` : "none",
              }} />
              <Badge color={backendStatus === "online" ? "green" : backendStatus === "offline" ? "red" : "amber"}>
                {backendStatus === "checking" ? "Checking" : backendStatus === "online" ? "Online" : "Offline"}
              </Badge>
            </div>
          }
        />
        <Row
          label="Production status"
          desc={platform ? `${platform.status} · ${platform.state.sessions_active} active sessions · ${platform.state.events_buffered} events buffered` : "Checking backend readiness"}
          action={<Badge color={platform?.ready ? "green" : "amber"}>{platform?.ready ? "Ready" : "Degraded"}</Badge>}
        />
        <Row
          label="Admin controls"
          desc={org ? `Public approval ${org.admin_controls.require_approval_for_public_actions ? "required" : "optional"} · external writes ${org.admin_controls.allow_agent_external_writes ? "enabled" : "approval-gated"}` : "Workspace controls load from the organization record"}
          action={<Badge>{org?.admin_controls.allowed_connectors.length ?? 0} connectors</Badge>}
        />
      </Section>

      {/* Production Gate */}
      <Section title="Production Gate">
        <div style={{ padding: 24, display: "grid", gap: 16 }}>

          {/* Launch readiness card */}
          <div style={{
            borderRadius: 12,
            border: `1px solid ${launchReadiness?.ok ? c.greenBorder : c.amberBorder}`,
            background: launchReadiness?.ok ? c.greenTint : c.amberTint,
            padding: 18, display: "grid", gap: 14,
          }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 14, flexWrap: "wrap" }}>
              <div>
                <p style={{ margin: 0, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: c.grey, fontWeight: 500 }}>Final launch readiness</p>
                <h2 style={{ margin: "7px 0 0", fontSize: 17, color: c.text, letterSpacing: "-0.01em", fontWeight: 600 }}>{launchReadiness?.summary ?? "Loading aggregate launch gate…"}</h2>
              </div>
              <Badge color={launchReadiness?.ok ? "green" : "amber"}>
                {launchReadiness?.ok ? "Launch proven" : `${launchReadiness?.failed?.length ?? 0} gates failing`}
              </Badge>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
              {(launchReadiness?.checks ?? []).slice(0, 8).map((check) => (
                <MiniCard key={check.key}>
                  <p style={{ margin: 0, fontSize: 10, color: c.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 500 }}>{check.key.replaceAll("_", " ")}</p>
                  <strong style={{ display: "block", marginTop: 5, fontSize: 13, color: check.ok ? c.green : c.amber }}>{check.ok ? "Pass" : "Needs proof"}</strong>
                </MiniCard>
              ))}
            </div>
            {!!launchReadiness?.failed?.length && (
              <div style={{ display: "grid", gap: 6 }}>
                {launchReadiness.failed.slice(0, 4).map((check) => (
                  <span key={check.key} style={{ fontSize: 12, color: c.textSecondary, lineHeight: 1.5 }}>· {check.key.replaceAll("_", " ")}: {check.message}</span>
                ))}
              </div>
            )}
            <MiniCard>
              <p style={{ margin: 0, fontSize: 10, color: c.textMuted, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 500 }}>Saved aggregate proof</p>
              <strong style={{ fontSize: 13, color: latestLaunchProof?.proof?.ok ? c.green : c.amber, display: "block", marginTop: 4 }}>
                {latestLaunchProof?.proof ? `${latestLaunchProof.proof.summary} · ${latestLaunchProof.proof.id}` : "No saved production launch proof yet."}
              </strong>
              {latestLaunchProof?.proof?.paths?.latest_json && (
                <span style={{ fontSize: 11, color: c.textMuted }}>{latestLaunchProof.proof.paths.latest_json}</span>
              )}
            </MiniCard>
          </div>

          {/* Verification header */}
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 16, color: c.text, letterSpacing: "-0.01em", fontWeight: 600 }}>Final deploy verification</h2>
              <p style={{ margin: "4px 0 0", fontSize: 13, color: c.grey, lineHeight: 1.6 }}>
                Runs strict smoke, live connector validation, deploy evidence checks, and writes JSON/Markdown proof.
              </p>
            </div>
            <Badge color={latestVerification?.ok ? "green" : "amber"}>
              {latestVerification?.ok ? "Verified" : "Proof needed"}
            </Badge>
          </div>

          {/* URL + Stack inputs */}
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.5fr) minmax(160px, 0.7fr)", gap: 12 }}>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: c.textMuted, fontWeight: 500 }}>Production API URL</span>
              <input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                style={inputStyle()}
                onFocus={e => (e.target.style.borderColor = c.blue)}
                onBlur={e => (e.target.style.borderColor = c.border)}
              />
            </label>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: c.textMuted, fontWeight: 500 }}>Stack</span>
              <input
                value={stackId}
                onChange={(event) => setStackId(event.target.value)}
                style={inputStyle()}
                onFocus={e => (e.target.style.borderColor = c.blue)}
                onBlur={e => (e.target.style.borderColor = c.border)}
              />
            </label>
          </div>

          {/* Controls row */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: c.textSecondary, cursor: "pointer" }}>
              <input type="checkbox" checked={liveConnectors} onChange={(event) => setLiveConnectors(event.target.checked)} style={{ accentColor: c.blue }} />
              Validate live connector credentials
            </label>
            <button
              onClick={runFinalVerification}
              disabled={verificationBusy || !baseUrl.trim() || !stackId.trim()}
              style={{
                fontSize: 13, padding: "8px 20px", borderRadius: 8,
                background: c.blue, color: "#FFFFFF", border: "none",
                cursor: verificationBusy || !baseUrl.trim() || !stackId.trim() ? "not-allowed" : "pointer",
                fontWeight: 500, opacity: verificationBusy ? 0.6 : 1,
              }}
            >
              {verificationBusy ? "Running…" : "Run final gate →"}
            </button>
          </div>

          {verificationError && (
            <div style={{ borderRadius: 10, border: `1px solid ${c.redBorder}`, background: c.redTint, color: c.red, padding: "12px 14px", fontSize: 13 }}>
              {verificationError}
            </div>
          )}

          {/* Two-column report cards */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <MiniCard style={{ minHeight: 132 }}>
              <p style={{ margin: 0, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: c.textMuted, fontWeight: 500 }}>Missing proof</p>
              <div style={{ marginTop: 10, display: "grid", gap: 7 }}>
                {(deployEvidence?.missing?.length ? deployEvidence.missing.slice(0, 6) : ["No deploy evidence loaded yet."]).map((item) => (
                  <span key={item} style={{ fontSize: 12, color: deployEvidence?.missing?.length ? c.textSecondary : c.textMuted, lineHeight: 1.5 }}>· {item}</span>
                ))}
              </div>
            </MiniCard>
            <MiniCard style={{ minHeight: 132 }}>
              <p style={{ margin: 0, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: c.textMuted, fontWeight: 500 }}>Latest report</p>
              <h3 style={{ margin: "10px 0 4px", fontSize: 14, color: c.text, fontWeight: 600 }}>{latestVerification?.summary ?? "No production verification report yet."}</h3>
              <p style={{ margin: 0, fontSize: 12, color: c.grey, lineHeight: 1.5 }}>
                {latestVerification?.created_at ? `${latestVerification.created_at} · ${latestVerification.stack_id}` : "Run the final gate after production env and connector credentials are configured."}
              </p>
              {latestVerification?.verification_command && (
                <code style={{ display: "block", marginTop: 10, fontSize: 11, color: c.textSecondary, lineHeight: 1.5, whiteSpace: "normal", background: c.surface, padding: "6px 8px", borderRadius: 6, border: `1px solid ${c.border}` }}>{latestVerification.verification_command}</code>
              )}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
                {latestVerification?.id && (
                  <a
                    href={productionVerificationMarkdownUrl(latestVerification.id)}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      fontSize: 12, padding: "5px 12px", borderRadius: 8,
                      background: c.bg, color: c.textSecondary, border: `1px solid ${c.border}`,
                      textDecoration: "none", fontWeight: 500, display: "inline-block",
                    }}
                  >
                    Open Markdown proof →
                  </a>
                )}
                {latestVerification?.id && (
                  <a
                    href={productionVerificationBundleUrl(latestVerification.id)}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      fontSize: 12, padding: "5px 12px", borderRadius: 8,
                      background: c.bg, color: c.textSecondary, border: `1px solid ${c.border}`,
                      textDecoration: "none", fontWeight: 500, display: "inline-block",
                    }}
                  >
                    Download proof bundle →
                  </a>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
                <button
                  onClick={verifyLatestManifest}
                  disabled={manifestBusy || !latestVerification?.id}
                  style={{
                    fontSize: 12, padding: "5px 12px", borderRadius: 8,
                    background: c.bg, color: c.textSecondary, border: `1px solid ${c.border}`,
                    cursor: manifestBusy || !latestVerification?.id ? "not-allowed" : "pointer",
                    opacity: manifestBusy || !latestVerification?.id ? 0.55 : 1,
                  }}
                >
                  {manifestBusy ? "Verifying…" : "Verify manifest"}
                </button>
                <span style={{ fontSize: 11, color: manifestVerification?.verified ? c.green : c.amber, fontWeight: 500 }}>
                  {manifestVerification?.verified ? "Checksum verified" : "Checksum not verified"}
                </span>
              </div>
            </MiniCard>
          </div>

          {/* Setup requirements */}
          <MiniCard>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div>
                <p style={{ margin: 0, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: c.textMuted, fontWeight: 500 }}>Setup requirements</p>
                <h3 style={{ margin: "7px 0 0", fontSize: 14, color: c.text, fontWeight: 600 }}>{requirements?.summary ?? "Loading production requirements…"}</h3>
              </div>
              <Badge color={requirements?.ok ? "green" : "amber"}>{requirements?.missing.length ?? 0} missing</Badge>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 14 }}>
              <div style={{ display: "grid", gap: 6 }}>
                {(requirements?.environment ?? []).slice(0, 8).map((item) => (
                  <div key={item.key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, fontSize: 12, color: c.textSecondary }}>
                    <span>{item.key}</span>
                    <span style={{ color: item.configured ? c.green : c.amber, fontWeight: 500 }}>{item.configured ? "set" : "missing"}</span>
                  </div>
                ))}
              </div>
              <div style={{ display: "grid", gap: 6 }}>
                {(requirements?.connectors ?? []).filter(connector => connector.required).map((connector) => (
                  <div key={connector.key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, fontSize: 12, color: c.textSecondary }}>
                    <span>{connector.label}</span>
                    <span style={{ color: c.textMuted }}>{connector.credential_fields.filter(field => field.required).map(field => field.key).join(", ")}</span>
                  </div>
                ))}
              </div>
            </div>
            {requirements?.final_gate.command && (
              <code style={{ display: "block", marginTop: 12, fontSize: 11, color: c.textSecondary, lineHeight: 1.6, whiteSpace: "normal", background: "#F3F4F6", padding: "8px 10px", borderRadius: 6, border: `1px solid ${c.border}` }}>{requirements.final_gate.command}</code>
            )}
          </MiniCard>

          {/* Objective evidence */}
          <MiniCard>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div>
                <p style={{ margin: 0, fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: c.textMuted, fontWeight: 500 }}>Objective evidence</p>
                <h3 style={{ margin: "7px 0 0", fontSize: 14, color: c.text, fontWeight: 600 }}>{requirements?.objective_evidence?.summary ?? "Loading objective evidence matrix…"}</h3>
              </div>
              <Badge color={requirements?.objective_evidence?.production_proven ? "green" : "amber"}>
                {requirements?.objective_evidence?.production_proven ? "Production proven" : "Live proof needed"}
              </Badge>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10, marginTop: 14 }}>
              {[
                {
                  label: "Code contract",
                  value: requirements?.objective_evidence?.code_contract_ready ? "Ready" : "Incomplete",
                  ok: requirements?.objective_evidence?.code_contract_ready,
                },
                {
                  label: "Live evidence",
                  value: requirements?.objective_evidence?.live_proof?.ok ? "Verified" : "Missing",
                  ok: requirements?.objective_evidence?.live_proof?.ok,
                },
                {
                  label: "Manifest",
                  value: (manifestVerification?.verified || requirements?.objective_evidence?.live_proof?.manifest_verified) ? "Verified" : "Needed",
                  ok: manifestVerification?.verified || requirements?.objective_evidence?.live_proof?.manifest_verified,
                },
              ].map(({ label, value, ok }) => (
                <div key={label} style={{
                  borderRadius: 8, border: `1px solid ${c.border}`,
                  padding: "12px", background: c.bg,
                }}>
                  <p style={{ margin: 0, fontSize: 10, color: c.textMuted, letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 500 }}>{label}</p>
                  <strong style={{ display: "block", marginTop: 6, fontSize: 15, color: ok ? c.green : c.amber }}>
                    {value}
                  </strong>
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gap: 7, marginTop: 14 }}>
              {(requirements?.objective_evidence?.requirements ?? []).map((item) => (
                <div key={item.key} style={{
                  display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto",
                  gap: 10, alignItems: "center", padding: "9px 12px",
                  borderRadius: 8, border: `1px solid ${c.border}`, background: c.bg,
                }}>
                  <span style={{ fontSize: 12, color: c.textSecondary, lineHeight: 1.4 }}>{item.requirement}</span>
                  <span style={{ fontSize: 11, color: statusHexColor(item.status, item.production_verified), fontWeight: 500, textTransform: "uppercase", whiteSpace: "nowrap" }}>
                    {item.status.replaceAll("_", " ")}
                  </span>
                </div>
              ))}
            </div>

            {requirements?.final_gate.verify_manifest_endpoint && (
              <code style={{ display: "block", marginTop: 12, fontSize: 11, color: c.textSecondary, lineHeight: 1.6, whiteSpace: "normal", background: "#F3F4F6", padding: "6px 10px", borderRadius: 6, border: `1px solid ${c.border}` }}>
                Verify manifest: {requirements.final_gate.verify_manifest_endpoint}
                {manifestVerification?.summary ? ` · ${manifestVerification.summary}` : ""}
              </code>
            )}
            {requirements?.final_gate.bundle_endpoint && (
              <code style={{ display: "block", marginTop: 6, fontSize: 11, color: c.textSecondary, lineHeight: 1.6, whiteSpace: "normal", background: "#F3F4F6", padding: "6px 10px", borderRadius: 6, border: `1px solid ${c.border}` }}>
                Export bundle: {requirements.final_gate.bundle_endpoint}
              </code>
            )}
          </MiniCard>
        </div>
      </Section>

      {/* Team */}
      <Section title="Team">
        <TeamSection founderId={founderId} org={org} />
      </Section>

      {/* Data */}
      <Section title="Data">
        <Row
          label="Session history"
          desc="Stored locally in your browser"
          action={
            <button
              onClick={() => { if (confirm("Clear all session history?")) { localStorage.removeItem("astra_sessions"); window.location.reload(); } }}
              style={{
                fontSize: 13, padding: "6px 14px", borderRadius: 8,
                color: c.red, background: c.redTint, border: `1px solid ${c.redBorder}`, cursor: "pointer",
              }}
            >
              Clear history
            </button>
          }
        />
      </Section>

      {/* Billing */}
      <Section title="Billing">
        <div style={{ padding: "16px 20px", display: "grid", gap: 16 }}>
          {/* Current plan card */}
          {org && (
            <div style={{
              display: "grid", gap: 0,
              borderRadius: 12, border: `1px solid ${c.border}`,
              overflow: "hidden",
            }}>
              {/* Plan header */}
              <div style={{
                padding: "14px 18px",
                background: `linear-gradient(135deg, ${c.blue} 0%, #1f36e0 100%)`,
                display: "flex", alignItems: "center", justifyContent: "space-between",
              }}>
                <div>
                  <p style={{ margin: 0, fontSize: 11, fontWeight: 600, color: "rgba(255,255,255,0.7)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Current Plan</p>
                  <p style={{ margin: "3px 0 0", fontSize: 20, fontWeight: 700, color: "#fff" }}>
                    {org.entitlements?.name ?? org.subscription?.plan ?? "Beta"}
                  </p>
                </div>
                <span style={{
                  fontSize: 11, padding: "4px 12px", borderRadius: 999, fontWeight: 600,
                  background: org.subscription?.status === "active" ? "rgba(255,255,255,0.2)" : "rgba(255,255,255,0.1)",
                  color: "#fff", border: "1px solid rgba(255,255,255,0.3)",
                  textTransform: "capitalize",
                }}>
                  {org.subscription?.status ?? "active"}
                </span>
              </div>

              {/* Plan details grid */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", borderTop: `1px solid ${c.border}` }}>
                {[
                  {
                    label: "Monthly Runs",
                    value: org.entitlements?.monthly_runs != null
                      ? `${org.usage?.runs ?? 0} / ${org.entitlements.monthly_runs === -1 ? "∞" : org.entitlements.monthly_runs}`
                      : "—",
                  },
                  {
                    label: "Team Seats",
                    value: org.entitlements?.team_seats != null
                      ? `${Object.keys(org.members ?? {}).length} / ${org.entitlements.team_seats === -1 ? "∞" : org.entitlements.team_seats}`
                      : "—",
                  },
                  {
                    label: "Connector Syncs / Day",
                    value: org.entitlements?.connector_syncs_per_day != null
                      ? (org.entitlements.connector_syncs_per_day === -1 ? "Unlimited" : String(org.entitlements.connector_syncs_per_day))
                      : "—",
                  },
                ].map(({ label, value }) => (
                  <div key={label} style={{
                    padding: "14px 18px",
                    borderRight: `1px solid ${c.border}`,
                  }}>
                    <p style={{ margin: 0, fontSize: 11, color: c.textMuted, fontWeight: 500 }}>{label}</p>
                    <p style={{ margin: "4px 0 0", fontSize: 15, fontWeight: 600, color: c.text }}>{value}</p>
                  </div>
                ))}
              </div>

              {/* Billing period */}
              {org.subscription?.current_period_end && (
                <div style={{ padding: "12px 18px", borderTop: `1px solid ${c.border}`, background: c.surface, display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 12, color: c.textMuted }}>Next billing date:</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: c.textSecondary }}>
                    {new Date(org.subscription.current_period_end).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" })}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Feature flags */}
          {org?.entitlements && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {[
                { label: "Approval Workflows", enabled: org.entitlements.approval_workflows },
                { label: "Company Brain", enabled: org.entitlements.company_brain },
              ].map(({ label, enabled }) => (
                <div key={label} style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "10px 14px", borderRadius: 10,
                  background: enabled ? c.greenTint : c.surface,
                  border: `1px solid ${enabled ? c.greenBorder : c.border}`,
                }}>
                  <span style={{ fontSize: 13, color: c.textSecondary, fontWeight: 500 }}>{label}</span>
                  <Badge color={enabled ? "green" : "grey"}>{enabled ? "Included" : "Upgrade"}</Badge>
                </div>
              ))}
            </div>
          )}

          {/* Available plans */}
          {billingConfig?.plans && Object.keys(billingConfig.plans).length > 0 && (
            <div style={{ display: "grid", gap: 8 }}>
              <p style={{ margin: 0, fontSize: 11, fontWeight: 600, color: c.textMuted, textTransform: "uppercase", letterSpacing: "0.07em" }}>Available Plans</p>
              <div style={{ display: "grid", gap: 6 }}>
                {Object.entries(billingConfig.plans).map(([planId, plan]) => {
                  const isCurrent = (org?.entitlements?.plan_id ?? org?.subscription?.plan) === planId;
                  return (
                    <div key={planId} style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: "12px 16px", borderRadius: 10,
                      border: `1px solid ${isCurrent ? c.blue : c.border}`,
                      background: isCurrent ? c.blueTint : c.bg,
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div>
                          <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: c.text }}>{plan.name}</p>
                          <p style={{ margin: "2px 0 0", fontSize: 11, color: c.textMuted }}>
                            {plan.monthly_runs === -1 ? "Unlimited" : plan.monthly_runs} runs · {plan.team_seats === -1 ? "Unlimited" : plan.team_seats} seats
                          </p>
                        </div>
                        {isCurrent && <Badge color="blue">Current</Badge>}
                      </div>
                      {!isCurrent && plan.self_serve && billingConfig.checkout_available && (
                        <button
                          disabled={billingBusy}
                          onClick={async () => {
                            setBillingBusy(true);
                            setBillingError("");
                            try {
                              const result = await createOrganizationCheckout(founderId, { plan: planId });
                              if (result.url) window.location.href = result.url;
                              else setBillingError(result.error ?? "Failed to start checkout.");
                            } catch (e) {
                              setBillingError(e instanceof Error ? e.message : "Failed to start checkout.");
                            } finally {
                              setBillingBusy(false);
                            }
                          }}
                          style={{
                            fontSize: 12, padding: "6px 14px", borderRadius: 8, cursor: "pointer",
                            background: c.blue, color: "#fff", border: "none", fontWeight: 600,
                            opacity: billingBusy ? 0.6 : 1,
                          }}
                        >
                          Upgrade
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {billingError && (
            <p style={{ margin: 0, fontSize: 12, color: c.red, background: c.redTint, border: `1px solid ${c.redBorder}`, borderRadius: 8, padding: "8px 12px" }}>
              {billingError}
            </p>
          )}

          {/* Manage billing portal */}
          {billingConfig?.portal_available && (
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                disabled={billingBusy}
                onClick={async () => {
                  setBillingBusy(true);
                  setBillingError("");
                  try {
                    const result = await createOrganizationBillingPortal(founderId);
                    if (result.url) window.location.href = result.url;
                    else setBillingError(result.error ?? "Failed to open billing portal.");
                  } catch (e) {
                    setBillingError(e instanceof Error ? e.message : "Failed to open billing portal.");
                  } finally {
                    setBillingBusy(false);
                  }
                }}
                style={{
                  fontSize: 13, padding: "7px 16px", borderRadius: 8, cursor: "pointer",
                  background: c.bg, color: c.textSecondary, border: `1px solid ${c.border}`, fontWeight: 500,
                  opacity: billingBusy ? 0.6 : 1,
                }}
              >
                Manage billing →
              </button>
            </div>
          )}
        </div>
      </Section>

    </div>
  );
}
