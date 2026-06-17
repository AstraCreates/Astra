"use client";

import { useEffect } from "react";
import { setApiAuthProvider } from "@/lib/api";
import { useDevUser, getOrCreateUserId } from "@/lib/use-dev-user";

export default function ApiAuthBridge() {
  const { userId, isSignedIn, isLoading } = useDevUser();

  useEffect(() => {
    // Avoid publishing a transient per-device ID while auth is still loading.
    if (isLoading) return;
    // Re-register whenever auth state resolves so the header always matches
    // the founderId used in URL params (prevents 403 on first load after sign-in).
    const resolvedId = isSignedIn ? userId : getOrCreateUserId();
    setApiAuthProvider(async () => ({ token: null, userId: resolvedId }));
    return () => setApiAuthProvider(null);
  }, [userId, isSignedIn, isLoading]);

  return null;
}
