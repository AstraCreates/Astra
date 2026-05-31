"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useUser, SignInButton } from "@clerk/nextjs";

interface InviteInfo {
  team_name: string;
  invited_by: string;
  expires_at?: string;
}

export default function AcceptInvitePage() {
  const params = useParams();
  const router = useRouter();
  const { user, isLoaded } = useUser();
  const token = params.token as string;

  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    if (!token) return;
    const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
    fetch(`${apiBase}/api/invites/${token}`)
      .then((res) => {
        if (!res.ok) {
          if (res.status === 410 || res.status === 404) throw new Error("This invite link has expired or is invalid.");
          throw new Error("Failed to load invite details.");
        }
        return res.json();
      })
      .then((data) => setInvite(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token]);

  async function handleAccept() {
    if (!user) return;
    setAccepting(true);
    setError(null);
    const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
    try {
      const res = await fetch(`${apiBase}/api/invites/${token}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ founder_id: user.id }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail ?? "Failed to accept invite.");
      }
      router.push("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setAccepting(false);
    }
  }

  // Not loaded yet
  if (!isLoaded || loading) {
    return (
      <div className="site-shell" style={{ paddingTop: 80, textAlign: "center" }}>
        <p style={{ opacity: 0.5 }}>Loading…</p>
      </div>
    );
  }

  // Not signed in
  if (!user) {
    return (
      <div className="site-shell" style={{ paddingTop: 80, textAlign: "center" }}>
        <div style={{ maxWidth: 420, margin: "0 auto" }}>
          <h1 style={{ marginBottom: 8 }}>You have an invite</h1>
          <p style={{ opacity: 0.6, marginBottom: 24 }}>Sign in to accept your team invitation.</p>
          <SignInButton mode="modal" redirectUrl={`/invite/${token}`}>
            <button className="site-btn site-btn-primary px-6">Sign in to continue</button>
          </SignInButton>
        </div>
      </div>
    );
  }

  // Error loading invite
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
      <div
        style={{
          maxWidth: 440,
          margin: "0 auto",
          background: "var(--surface, rgba(255,255,255,0.04))",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: 16,
          padding: "40px 36px",
        }}
      >
        <div
          style={{
            width: 56,
            height: 56,
            borderRadius: "50%",
            background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
            margin: "0 auto 20px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 24,
          }}
        >
          🚀
        </div>
        <h1 style={{ marginBottom: 8, fontSize: 22 }}>You're invited</h1>
        {invite && (
          <>
            <p style={{ opacity: 0.7, marginBottom: 4 }}>
              You've been invited to join
            </p>
            <p style={{ fontSize: 20, fontWeight: 700, marginBottom: 28 }}>{invite.team_name}</p>
          </>
        )}

        {error && (
          <p style={{ color: "var(--color-error, #f87171)", marginBottom: 16, fontSize: 14 }}>{error}</p>
        )}

        <button
          className="site-btn site-btn-primary"
          style={{ width: "100%", justifyContent: "center", padding: "10px 0", fontSize: 15 }}
          onClick={handleAccept}
          disabled={accepting}
        >
          {accepting ? "Joining…" : "Accept & Join"}
        </button>

        <p style={{ marginTop: 16, opacity: 0.4, fontSize: 12 }}>
          Joining as {user.primaryEmailAddress?.emailAddress ?? user.id}
        </p>
      </div>
    </div>
  );
}
