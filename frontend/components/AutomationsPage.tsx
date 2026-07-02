"use client";

import { useEffect, useRef, useState } from "react";
import { useDevUser } from "@/lib/use-dev-user";
import { apiFetch, waitForAuthReady } from "@/lib/api";
import PageHeader from "@/components/PageHeader";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const AUTOMATIONS_ORIGIN = "https://automations.178.105.231.73.nip.io";
const BRIDGE_URL = `${AUTOMATIONS_ORIGIN}/astra-bridge.html`;

// SSO into the self-hosted automations builder. Activepieces' own embed-sdk
// (managed auth) is Enterprise-only — this gets a founder logged in without
// ever seeing an Activepieces login screen using only its public sign-in API:
// backend provisions + signs in server-side, this page hands the resulting
// token to a same-origin bridge page via postMessage, which stores it and
// redirects into the real app already authenticated. See
// backend/tools/automations_bridge.py and deploy/automations-bridge.html.
export default function AutomationsPage() {
  const { userId } = useDevUser();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [bridgeReady, setBridgeReady] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    if (!userId || userId === "anon") return;
    let cancelled = false;
    // ApiAuthBridge fetches the real Bearer token asynchronously on mount.
    // Without waiting, this can fire first and fall back to the (now
    // rejected) trusted x-astra-user-id header, 401ing intermittently.
    waitForAuthReady()
      .then(() => apiFetch(`${BASE}/automations/session?founder_id=${encodeURIComponent(userId)}`))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data) => {
        if (!cancelled && data?.token) {
          setToken(data.token);
          setStatus("ready");
        } else if (!cancelled) {
          setStatus("error");
        }
      })
      .catch(() => { if (!cancelled) setStatus("error"); });
    return () => { cancelled = true; };
  }, [userId]);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (event.origin !== AUTOMATIONS_ORIGIN) return;
      if (event.data?.type === "astra-automations-bridge-ready") {
        setBridgeReady(true);
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  useEffect(() => {
    if (bridgeReady && token && iframeRef.current?.contentWindow) {
      iframeRef.current.contentWindow.postMessage(
        { type: "astra-automations-auth", token },
        AUTOMATIONS_ORIGIN
      );
    }
  }, [bridgeReady, token]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <PageHeader title="Automations" subtitle="Build workflows that connect your tools" />
      <div style={{ flex: 1, position: "relative", background: "var(--s2)" }}>
        {status === "loading" && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--fm)" }}>
            Loading…
          </div>
        )}
        {status === "error" && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--fm)" }}>
            Couldn&apos;t load automations. Try refreshing.
          </div>
        )}
        {status === "ready" && (
          <iframe
            ref={iframeRef}
            src={BRIDGE_URL}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", border: "none" }}
            title="Automations"
          />
        )}
      </div>
    </div>
  );
}
