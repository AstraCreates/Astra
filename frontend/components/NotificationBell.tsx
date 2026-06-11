"use client";
import { useEffect, useState, useCallback } from "react";
import { useDevUser } from "@/lib/use-dev-user";

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  return new Uint8Array(Array.from(raw).map((c) => c.charCodeAt(0)));
}

async function doSubscribe(userId: string): Promise<void> {
  const reg = await navigator.serviceWorker.ready;
  const keyRes = await fetch("/api/notifications/vapid-public-key");
  const { publicKey } = await keyRes.json();
  if (!publicKey) return;
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(publicKey),
  });
  await fetch("/api/notifications/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: userId, subscription: sub.toJSON() }),
  });
}

export default function NotificationBell() {
  const { userId } = useDevUser();
  const [permission, setPermission] = useState<NotificationPermission | null>(null);
  const [subscribed, setSubscribed] = useState(false);

  useEffect(() => {
    if (typeof Notification === "undefined") return;
    setPermission(Notification.permission);
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
  }, []);

  const enable = useCallback(async () => {
    if (!("Notification" in window) || !("serviceWorker" in navigator)) return;
    const perm = await Notification.requestPermission();
    setPermission(perm);
    if (perm !== "granted") return;
    try {
      await doSubscribe(userId);
      setSubscribed(true);
    } catch (e) {
      console.error("Notification subscribe failed", e);
    }
  }, [userId]);

  // Auto-subscribe silently when permission already granted
  useEffect(() => {
    if (permission === "granted" && !subscribed && userId) {
      doSubscribe(userId)
        .then(() => setSubscribed(true))
        .catch(() => {});
    }
  }, [permission, subscribed, userId]);

  if (!permission || permission === "granted" || permission === "denied") return null;

  return (
    <button
      onClick={enable}
      title="Get notified when runs complete"
      style={{
        display: "flex", alignItems: "center", gap: 6, width: "100%",
        padding: "5px 8px", marginBottom: 8,
        background: "var(--s2)", border: "1px solid var(--bd)",
        cursor: "pointer", borderRadius: 3, textAlign: "left",
      }}
    >
      <span style={{ fontSize: 11 }}>🔔</span>
      <span style={{ fontSize: 10.5, fontWeight: 500, color: "var(--fg-muted)" }}>
        Enable notifications
      </span>
    </button>
  );
}
