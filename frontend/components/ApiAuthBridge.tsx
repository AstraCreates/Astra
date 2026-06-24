"use client";

import { useEffect, useRef } from "react";
import { setApiAuthProvider } from "@/lib/api";
import { useDevUser, getOrCreateUserId } from "@/lib/use-dev-user";

export default function ApiAuthBridge() {
  const { userId, isSignedIn, isLoading } = useDevUser();
  const bearerRef = useRef<string | null>(null);

  // Fetch the HS256 session JWT from the server-side token route when signed in.
  // Stored in a ref (not state) to avoid re-renders — only used as auth header value.
  useEffect(() => {
    if (!isSignedIn) {
      bearerRef.current = null;
      return;
    }
    fetch("/api/auth/token")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { token?: string } | null) => {
        bearerRef.current = d?.token ?? null;
      })
      .catch(() => {});
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
