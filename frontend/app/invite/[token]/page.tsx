"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useDevUser } from "@/lib/use-dev-user";
import { acceptOrganizationInvite, getOrganizationInvite, type OrganizationInvite } from "@/lib/api";

export default function AcceptInvitePage() {
  const params = useParams();
  const router = useRouter();
  const { userId } = useDevUser();
  const token = params.token as string;

  const [invite, setInvite] = useState<OrganizationInvite | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    if (!token) return;
    getOrganizationInvite(token)
      .then(setInvite)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load invite details."))
      .finally(() => setLoading(false));
  }, [token]);

  async function handleAccept() {
    if (!userId || userId === "anon") return;
    setAccepting(true);
    setError(null);
    try {
      await acceptOrganizationInvite(token, userId);
      router.push("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setAccepting(false);
    }
  }

  if (loading) {
    return <div className="site-shell" style={{ paddingTop: 80, textAlign: "center" }}><p style={{ opacity: 0.5 }}>Loading…</p></div>;
  }

  if (error && !invite) {
    return (
      <div className="site-shell" style={{ paddingTop: 80, textAlign: "center" }}>
        <div style={{ maxWidth: 420, margin: "0 auto" }}>
          <h1 style={{ marginBottom: 8 }}>Invite unavailable</h1>
          <p style={{ opacity: 0.6, marginBottom: 24 }}>{error}</p>
          <a href="/" className="site-btn site-btn-ghost px-4">Go home</a>
        </div>
      </div>
    );
  }

  return (
    <div className="site-shell" style={{ paddingTop: 80, textAlign: "center" }}>
      <div style={{ maxWidth: 440, margin: "0 auto", background: "var(--surface, rgba(255,255,255,0.04))", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 16, padding: "40px 36px" }}>
        <div style={{ width: 56, height: 56, borderRadius: "50%", background: "linear-gradient(135deg, #6366f1, #8b5cf6)", margin: "0 auto 20px", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24 }}>▲</div>
        <h1 style={{ marginBottom: 8, fontSize: 22 }}>You&apos;re invited</h1>
        {invite && (
          <>
            <p style={{ opacity: 0.7, marginBottom: 4 }}>You&apos;ve been invited to join</p>
            <p style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>{invite.org_name || invite.org_id}</p>
            <p style={{ opacity: 0.6, marginBottom: 28, fontSize: 13 }}>Role: {invite.role || "viewer"}{invite.email ? ` · ${invite.email}` : ""}</p>
          </>
        )}

        {error && <p style={{ color: "var(--color-error, #f87171)", marginBottom: 16, fontSize: 14 }}>{error}</p>}

        <button className="site-btn site-btn-primary" style={{ width: "100%", justifyContent: "center", padding: "10px 0", fontSize: 15 }} onClick={handleAccept} disabled={accepting}>
          {accepting ? "Joining…" : "Accept & Join"}
        </button>

        <p style={{ marginTop: 16, opacity: 0.4, fontSize: 12 }}>
          Joining as Dev User ({userId.slice(0, 12)})
        </p>
      </div>
    </div>
  );
}
