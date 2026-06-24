"use client";

import { useEffect, useRef } from "react";
import { setApiAuthProvider, _setCachedAuthToken } from "@/lib/api";
import { useDevUser, getOrCreateUserId } from "@/lib/use-dev-user";

export default function ApiAuthBridge() {
  const { userId, isSignedIn, isLoading } = useDevUser();
  const bearerRef = useRef<string | null>(null);
  const bearerExpiryRef = useRef<number>(0);

  // Fetch the HS256 session JWT from the server-side token route when signed in.
  // Stored in a ref (not state) to avoid re-renders — only used as auth header value.
  useEffect(() => {
    let cancelled = false;
    const refreshBearer = async () => {
      try {
        const res = await fetch("/api/auth/token");
        const data = res.ok ? await res.json() : null;
        if (cancelled) return;
        bearerRef.current = data?.token ?? null;
        _setCachedAuthToken(bearerRef.current);
        try {
          const rawPayload = bearerRef.current?.split(".")[1] || "";
          const normalized = rawPayload.replace(/-/g, "+").replace(/_/g, "/");
          const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
          const payload = bearerRef.current ? JSON.parse(atob(padded)) : null;
          bearerExpiryRef.current = Number(payload?.exp || 0) * 1000;
        } catch {
          bearerExpiryRef.current = 0;
        }
      } catch {
        if (!cancelled) {
          bearerRef.current = null;
          bearerExpiryRef.current = 0;
        }
      }
    };
    if (!isSignedIn) {
      bearerRef.current = null;
      bearerExpiryRef.current = 0;
      _setCachedAuthToken(null);
      return;
    }
    void refreshBearer();
    const interval = window.setInterval(() => {
      const expiresSoon = !bearerExpiryRef.current || (bearerExpiryRef.current - Date.now()) < 5 * 60_000;
      if (expiresSoon) void refreshBearer();
    }, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [isSignedIn]);

  useEffect(() => {
    if (isLoading) return;
    const resolvedId = isSignedIn ? userId : getOrCreateUserId();
    setApiAuthProvider(async () => ({
      token: bearerRef.current,
      userId: resolvedId,
    }));
    return () => setApiAuthProvider(null);
  }, [userId, isSignedIn, isLoading]);

  return null;
}
