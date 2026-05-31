"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { UserButton, useUser } from "@clerk/nextjs";
import ThemeToggle from "@/components/ThemeToggle";
import {
  getDeployEvidence,
  getLaunchReadiness,
  getOrganization,
  getPlatformStatus,
  getProductionLaunchProof,
  getProductionRequirements,
  getProductionVerificationReports,
  productionVerificationBundleUrl,
  productionVerificationMarkdownUrl,
  runProductionLaunch,
  verifyProductionVerificationManifest,
  type DeployEvidenceReport,
  type LaunchReadiness,
  type OrganizationAccount,
  type PlatformStatus,
  type ProductionLaunchProofResponse,
  type ProductionRequirements,
  type ProductionVerificationManifestVerification,
  type ProductionVerificationReport,
} from "@/lib/api";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 1, borderRadius: 28, overflow: "hidden", border: "1px solid var(--line)", background: "var(--glass)", backdropFilter: "var(--blur)", WebkitBackdropFilter: "var(--blur)", boxShadow: "var(--shadow-sm)" }}>
      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--line-2)" }}>
        <span style={{ fontSize: 11, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>{title}</span>
      </div>
      {children}
    </div>
  );
}

function Row({ label, desc, action }: { label: string; desc?: string; action: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20, padding: "14px 20px", borderBottom: "1px solid var(--line-2)" }}>
      <div>
        <p style={{ margin: 0, fontSize: 13, color: "var(--fg)", fontWeight: 500 }}>{label}</p>
        {desc && <p style={{ margin: "2px 0 0", fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.4 }}>{desc}</p>}
      </div>
      {action}
    </div>
  );
}

function statusColor(status: string, ok?: boolean) {
  if (ok || status === "code_ready" || status === "production_verified") return "#3D9E5F";
  if (status === "needs_live_proof") return "#D97706";
  return "#C97070";
}

export default function SettingsPage() {
  const { user, isLoaded } = useUser();
  const founderId = user?.id ?? "founder_001";
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

  useEffect(() => {
    if (!isLoaded) return;
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
    ]).then(([platformResult, orgResult, verificationResult, evidenceResult, requirementsResult, manifestResult, readinessResult, launchProofResult]) => {
      if (cancelled) return;
      if (platformResult.status === "fulfilled") setPlatform(platformResult.value);
      if (orgResult.status === "fulfilled") setOrg(orgResult.value);
      if (verificationResult.status === "fulfilled") setLatestVerification(verificationResult.value.latest);
      if (evidenceResult.status === "fulfilled") setDeployEvidence(evidenceResult.value);
      if (requirementsResult.status === "fulfilled") setRequirements(requirementsResult.value);
      if (manifestResult.status === "fulfilled") setManifestVerification(manifestResult.value);
      if (readinessResult.status === "fulfilled") setLaunchReadiness(readinessResult.value);
      if (launchProofResult.status === "fulfilled") setLatestLaunchProof(launchProofResult.value);
    });
    return () => { cancelled = true; };
  }, [founderId, isLoaded, stackId, baseUrl]);

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
    <div style={{ width: "100%", maxWidth: 920, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Link href="/" className="site-btn site-btn-ghost" style={{ padding: "0 14px", fontSize: 12 }}>
            ← Back
          </Link>
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0, color: "var(--fg)", letterSpacing: "-0.02em" }}>Settings</h1>
            <p style={{ fontSize: 13, color: "var(--fg-mute)", margin: "4px 0 0" }}>Manage your account and preferences</p>
          </div>
        </div>
        <ThemeToggle />
      </div>

      <Section title="Account">
        <Row label="Profile" desc={user?.primaryEmailAddress?.emailAddress ?? "Manage your Clerk account"} action={<UserButton />} />
        <Row label="Plan" desc={org ? `${org.entitlements.remaining_runs}/${org.entitlements.monthly_runs} runs remaining · ${org.entitlements.remaining_team_seats} seats open` : "Developer workspace during beta"} action={<span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 999, background: "var(--glass-hi)", color: "var(--fg-dim)", border: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>{org?.entitlements.name ?? "Beta"}</span>} />
        <Row label="Team access" desc={org ? `${Object.values(org.members).filter(member => member.status === "active").length} active member(s) · owner ${org.owner_id}` : "Team roles load from the organization control plane"} action={<span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 999, background: "var(--glass-hi)", color: "var(--fg-dim)", border: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>Roles</span>} />
      </Section>

      <Section title="Integrations">
        <Row label="GitHub · Vercel · Supabase · Composio" desc="Connect accounts for full agent capabilities" action={
          <Link href="/integrations" className="site-btn site-btn-ghost" style={{ fontSize: 12, padding: "0 14px", minHeight: 34 }}>
            Manage →
          </Link>
        } />
        <Row label="Stripe" desc="Connect payment context for launch and revenue work" action={<span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 999, background: "var(--glass-hi)", color: "var(--fg-dim)", border: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>Managed in integrations</span>} />
      </Section>

      <Section title="Onboarding">
        <Row
          label="Restart onboarding"
          desc="Re-run the setup wizard to change your stack or reconnect integrations"
          action={
            <button
              onClick={() => { localStorage.removeItem("astra_onboarding_done"); window.location.href = "/onboarding"; }}
              className="site-btn site-btn-ghost"
              style={{ fontSize: 12, padding: "0 14px", minHeight: 34 }}
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
              className="site-btn site-btn-ghost"
              style={{ fontSize: 12, padding: "0 14px", minHeight: 34 }}
            >
              Take tour →
            </button>
          }
        />
      </Section>

      <Section title="Notifications">
        <Row label="Browser notifications" desc="Get notified when a goal completes" action={
          <button
            onClick={() => Notification.requestPermission()}
            className="site-btn site-btn-primary"
            style={{ fontSize: 12, padding: "0 14px", minHeight: 34 }}
          >
            Enable
          </button>
        } />
      </Section>

      <Section title="Platform">
        <Row label="Production status" desc={platform ? `${platform.status} · ${platform.state.sessions_active} active sessions · ${platform.state.events_buffered} events buffered` : "Checking backend readiness"} action={
          <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 999, background: platform?.ready ? "rgba(61,158,95,0.12)" : "rgba(245,158,11,0.12)", color: platform?.ready ? "#3D9E5F" : "#D97706", border: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>
            {platform?.ready ? "Ready" : "Degraded"}
          </span>
        } />
        <Row label="Admin controls" desc={org ? `Public approval ${org.admin_controls.require_approval_for_public_actions ? "required" : "optional"} · external writes ${org.admin_controls.allow_agent_external_writes ? "enabled" : "approval-gated"}` : "Workspace controls load from the organization record"} action={
          <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 999, background: "var(--glass-hi)", color: "var(--fg-dim)", border: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>
            {org?.admin_controls.allowed_connectors.length ?? 0} connectors
          </span>
        } />
      </Section>

      <Section title="Production Gate">
        <div style={{ padding: 20, display: "grid", gap: 14 }}>
          <div style={{ borderRadius: 24, border: "1px solid var(--line)", background: launchReadiness?.ok ? "rgba(61,158,95,0.10)" : "rgba(245,158,11,0.10)", padding: 16, display: "grid", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 14, flexWrap: "wrap" }}>
              <div>
                <p style={{ margin: 0, fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>Final launch readiness</p>
                <h2 style={{ margin: "7px 0 0", fontSize: 17, color: "var(--fg)", letterSpacing: "-0.01em" }}>{launchReadiness?.summary ?? "Loading aggregate launch gate…"}</h2>
              </div>
              <span style={{ fontSize: 11, padding: "4px 10px", borderRadius: 999, background: launchReadiness?.ok ? "rgba(61,158,95,0.14)" : "rgba(245,158,11,0.14)", color: launchReadiness?.ok ? "#3D9E5F" : "#D97706", border: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>
                {launchReadiness?.ok ? "Launch proven" : `${launchReadiness?.failed?.length ?? 0} gates failing`}
              </span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
              {(launchReadiness?.checks ?? []).slice(0, 8).map((check) => (
                <div key={check.key} style={{ borderRadius: 16, border: "1px solid var(--line-2)", background: "rgba(255,255,255,0.025)", padding: "9px 10px" }}>
                  <p style={{ margin: 0, fontSize: 10, color: "var(--fg-mute)", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}>{check.key.replaceAll("_", " ")}</p>
                  <strong style={{ display: "block", marginTop: 5, fontSize: 12, color: check.ok ? "#3D9E5F" : "#D97706" }}>{check.ok ? "Pass" : "Needs proof"}</strong>
                </div>
              ))}
            </div>
            {!!launchReadiness?.failed?.length && (
              <div style={{ display: "grid", gap: 6 }}>
                {launchReadiness.failed.slice(0, 4).map((check) => (
                  <span key={check.key} style={{ fontSize: 12, color: "var(--fg-dim)", lineHeight: 1.4 }}>· {check.key.replaceAll("_", " ")}: {check.message}</span>
                ))}
              </div>
            )}
            <div style={{ borderRadius: 18, border: "1px solid var(--line-2)", background: "rgba(255,255,255,0.025)", padding: "10px 12px", display: "grid", gap: 4 }}>
              <p style={{ margin: 0, fontSize: 10, color: "var(--fg-mute)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.10em" }}>Saved aggregate proof</p>
              <strong style={{ fontSize: 13, color: latestLaunchProof?.proof?.ok ? "#3D9E5F" : "#D97706" }}>
                {latestLaunchProof?.proof ? `${latestLaunchProof.proof.summary} · ${latestLaunchProof.proof.id}` : "No saved production launch proof yet."}
              </strong>
              {latestLaunchProof?.proof?.paths?.latest_json && (
                <span style={{ fontSize: 10, color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>{latestLaunchProof.proof.paths.latest_json}</span>
              )}
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 16, color: "var(--fg)", letterSpacing: "-0.01em" }}>Final deploy verification</h2>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--fg-mute)", lineHeight: 1.5 }}>
                Runs strict smoke, live connector validation, deploy evidence checks, and writes JSON/Markdown proof.
              </p>
            </div>
            <span style={{ fontSize: 11, padding: "4px 10px", borderRadius: 999, background: latestVerification?.ok ? "rgba(61,158,95,0.12)" : "rgba(245,158,11,0.12)", color: latestVerification?.ok ? "#3D9E5F" : "#D97706", border: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>
              {latestVerification?.ok ? "Verified" : "Proof needed"}
            </span>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.5fr) minmax(160px, 0.7fr)", gap: 12 }}>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>Production API URL</span>
              <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)}
                style={{ width: "100%", minHeight: 42, borderRadius: 18, border: "1px solid var(--line)", background: "var(--glass-hi)", color: "var(--fg)", padding: "0 14px", outline: "none" }}
              />
            </label>
            <label style={{ display: "grid", gap: 6 }}>
              <span style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>Stack</span>
              <input value={stackId} onChange={(event) => setStackId(event.target.value)}
                style={{ width: "100%", minHeight: 42, borderRadius: 18, border: "1px solid var(--line)", background: "var(--glass-hi)", color: "var(--fg)", padding: "0 14px", outline: "none" }}
              />
            </label>
          </div>

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--fg-dim)" }}>
              <input type="checkbox" checked={liveConnectors} onChange={(event) => setLiveConnectors(event.target.checked)} />
              Validate live connector credentials
            </label>
            <button onClick={runFinalVerification} disabled={verificationBusy || !baseUrl.trim() || !stackId.trim()}
              className="site-btn site-btn-primary"
              style={{ fontSize: 12, padding: "0 16px", minHeight: 36, opacity: verificationBusy ? 0.6 : 1 }}
            >
              {verificationBusy ? "Running…" : "Run final gate →"}
            </button>
          </div>

          {verificationError && (
            <div style={{ borderRadius: 18, border: "1px solid rgba(180,60,60,0.25)", background: "rgba(180,60,60,0.10)", color: "#C97070", padding: "10px 12px", fontSize: 12 }}>
              {verificationError}
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div style={{ borderRadius: 22, border: "1px solid var(--line)", background: "var(--glass-hi)", padding: 14, minHeight: 132 }}>
              <p style={{ margin: 0, fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>Missing proof</p>
              <div style={{ marginTop: 10, display: "grid", gap: 7 }}>
                {(deployEvidence?.missing?.length ? deployEvidence.missing.slice(0, 6) : ["No deploy evidence loaded yet."]).map((item) => (
                  <span key={item} style={{ fontSize: 12, color: deployEvidence?.missing?.length ? "var(--fg-dim)" : "var(--fg-mute)", lineHeight: 1.45 }}>· {item}</span>
                ))}
              </div>
            </div>
            <div style={{ borderRadius: 22, border: "1px solid var(--line)", background: "var(--glass-hi)", padding: 14, minHeight: 132 }}>
              <p style={{ margin: 0, fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>Latest report</p>
              <h3 style={{ margin: "10px 0 4px", fontSize: 14, color: "var(--fg)" }}>{latestVerification?.summary ?? "No production verification report yet."}</h3>
              <p style={{ margin: 0, fontSize: 11, color: "var(--fg-mute)", lineHeight: 1.45 }}>
                {latestVerification?.created_at ? `${latestVerification.created_at} · ${latestVerification.stack_id}` : "Run the final gate after production env and connector credentials are configured."}
              </p>
              {latestVerification?.verification_command && (
                <code style={{ display: "block", marginTop: 10, fontSize: 10, color: "var(--fg-dim)", lineHeight: 1.5, whiteSpace: "normal" }}>{latestVerification.verification_command}</code>
              )}
              {latestVerification?.id && (
                <a
                  href={productionVerificationMarkdownUrl(latestVerification.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="site-btn site-btn-ghost"
                  style={{ display: "inline-flex", marginTop: 12, fontSize: 11, padding: "0 12px", minHeight: 30, textDecoration: "none" }}
                >
                Open Markdown proof →
              </a>
              )}
              {latestVerification?.id && (
                <a
                  href={productionVerificationBundleUrl(latestVerification.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="site-btn site-btn-ghost"
                  style={{ display: "inline-flex", marginTop: 8, marginLeft: 8, fontSize: 11, padding: "0 12px", minHeight: 30, textDecoration: "none" }}
                >
                  Download proof bundle →
                </a>
              )}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                <button
                  onClick={verifyLatestManifest}
                  disabled={manifestBusy || !latestVerification?.id}
                  className="site-btn site-btn-ghost"
                  style={{ fontSize: 11, padding: "0 12px", minHeight: 30, opacity: manifestBusy || !latestVerification?.id ? 0.55 : 1 }}
                >
                  {manifestBusy ? "Verifying…" : "Verify manifest"}
                </button>
                <span style={{ fontSize: 10, color: manifestVerification?.verified ? "#3D9E5F" : "#D97706", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}>
                  {manifestVerification?.verified ? "Checksum verified" : "Checksum not verified"}
                </span>
              </div>
            </div>
          </div>

          <div style={{ borderRadius: 22, border: "1px solid var(--line)", background: "var(--glass-hi)", padding: 14 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div>
                <p style={{ margin: 0, fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>Setup requirements</p>
                <h3 style={{ margin: "7px 0 0", fontSize: 14, color: "var(--fg)" }}>{requirements?.summary ?? "Loading production requirements…"}</h3>
              </div>
              <span style={{ fontSize: 11, padding: "4px 10px", borderRadius: 999, background: requirements?.ok ? "rgba(61,158,95,0.12)" : "rgba(245,158,11,0.12)", color: requirements?.ok ? "#3D9E5F" : "#D97706", border: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>
                {requirements?.missing.length ?? 0} missing
              </span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
              <div style={{ display: "grid", gap: 6 }}>
                {(requirements?.environment ?? []).slice(0, 8).map((item) => (
                  <div key={item.key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, fontSize: 11, color: "var(--fg-dim)" }}>
                    <span>{item.key}</span>
                    <span style={{ color: item.configured ? "#3D9E5F" : "#D97706", fontFamily: "var(--font-mono)" }}>{item.configured ? "set" : "missing"}</span>
                  </div>
                ))}
              </div>
              <div style={{ display: "grid", gap: 6 }}>
                {(requirements?.connectors ?? []).filter(connector => connector.required).map((connector) => (
                  <div key={connector.key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, fontSize: 11, color: "var(--fg-dim)" }}>
                    <span>{connector.label}</span>
                    <span style={{ color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>{connector.credential_fields.filter(field => field.required).map(field => field.key).join(", ")}</span>
                  </div>
                ))}
              </div>
            </div>
            {requirements?.final_gate.command && (
              <code style={{ display: "block", marginTop: 12, fontSize: 10, color: "var(--fg-dim)", lineHeight: 1.5, whiteSpace: "normal" }}>{requirements.final_gate.command}</code>
            )}
          </div>

          <div style={{ borderRadius: 22, border: "1px solid var(--line)", background: "var(--glass-hi)", padding: 14 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div>
                <p style={{ margin: 0, fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-mute)", fontFamily: "var(--font-mono)" }}>Objective evidence</p>
                <h3 style={{ margin: "7px 0 0", fontSize: 14, color: "var(--fg)" }}>{requirements?.objective_evidence?.summary ?? "Loading objective evidence matrix…"}</h3>
              </div>
              <span style={{ fontSize: 11, padding: "4px 10px", borderRadius: 999, background: requirements?.objective_evidence?.production_proven ? "rgba(61,158,95,0.12)" : "rgba(245,158,11,0.12)", color: requirements?.objective_evidence?.production_proven ? "#3D9E5F" : "#D97706", border: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>
                {requirements?.objective_evidence?.production_proven ? "Production proven" : "Live proof needed"}
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10, marginTop: 12 }}>
              <div style={{ borderRadius: 18, border: "1px solid var(--line-2)", padding: 12, background: "rgba(255,255,255,0.03)" }}>
                <p style={{ margin: 0, fontSize: 10, color: "var(--fg-mute)", letterSpacing: "0.10em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>Code contract</p>
                <strong style={{ display: "block", marginTop: 6, fontSize: 15, color: requirements?.objective_evidence?.code_contract_ready ? "#3D9E5F" : "#C97070" }}>
                  {requirements?.objective_evidence?.code_contract_ready ? "Ready" : "Incomplete"}
                </strong>
              </div>
              <div style={{ borderRadius: 18, border: "1px solid var(--line-2)", padding: 12, background: "rgba(255,255,255,0.03)" }}>
                <p style={{ margin: 0, fontSize: 10, color: "var(--fg-mute)", letterSpacing: "0.10em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>Live evidence</p>
                <strong style={{ display: "block", marginTop: 6, fontSize: 15, color: requirements?.objective_evidence?.live_proof?.ok ? "#3D9E5F" : "#D97706" }}>
                  {requirements?.objective_evidence?.live_proof?.ok ? "Verified" : "Missing"}
                </strong>
              </div>
              <div style={{ borderRadius: 18, border: "1px solid var(--line-2)", padding: 12, background: "rgba(255,255,255,0.03)" }}>
                <p style={{ margin: 0, fontSize: 10, color: "var(--fg-mute)", letterSpacing: "0.10em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>Manifest</p>
                <strong style={{ display: "block", marginTop: 6, fontSize: 15, color: manifestVerification?.verified || requirements?.objective_evidence?.live_proof?.manifest_verified ? "#3D9E5F" : "#D97706" }}>
                  {manifestVerification?.verified || requirements?.objective_evidence?.live_proof?.manifest_verified ? "Verified" : "Needed"}
                </strong>
              </div>
            </div>

            <div style={{ display: "grid", gap: 7, marginTop: 12 }}>
              {(requirements?.objective_evidence?.requirements ?? []).map((item) => (
                <div key={item.key} style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 10, alignItems: "center", padding: "9px 10px", borderRadius: 16, border: "1px solid var(--line-2)", background: "rgba(255,255,255,0.025)" }}>
                  <span style={{ fontSize: 11, color: "var(--fg-dim)", lineHeight: 1.35 }}>{item.requirement}</span>
                  <span style={{ fontSize: 10, color: statusColor(item.status, item.production_verified), fontFamily: "var(--font-mono)", textTransform: "uppercase", whiteSpace: "nowrap" }}>
                    {item.status.replaceAll("_", " ")}
                  </span>
                </div>
              ))}
            </div>

            {requirements?.final_gate.verify_manifest_endpoint && (
              <code style={{ display: "block", marginTop: 12, fontSize: 10, color: "var(--fg-dim)", lineHeight: 1.5, whiteSpace: "normal" }}>
                Verify manifest: {requirements.final_gate.verify_manifest_endpoint}
                {manifestVerification?.summary ? ` · ${manifestVerification.summary}` : ""}
              </code>
            )}
            {requirements?.final_gate.bundle_endpoint && (
              <code style={{ display: "block", marginTop: 6, fontSize: 10, color: "var(--fg-dim)", lineHeight: 1.5, whiteSpace: "normal" }}>
                Export bundle: {requirements.final_gate.bundle_endpoint}
              </code>
            )}
          </div>
        </div>
      </Section>

      <Section title="Data">
        <Row label="Session history" desc="Stored locally in your browser" action={
          <button onClick={() => { if (confirm("Clear all session history?")) { localStorage.removeItem("astra_sessions"); window.location.reload(); } }}
            className="site-btn"
            style={{ fontSize: 12, padding: "0 14px", minHeight: 34, color: "#C97070", background: "rgba(180,60,60,0.10)", borderColor: "rgba(180,60,60,0.20)" }}
          >
            Clear history
          </button>
        } />
      </Section>
    </div>
  );
}
