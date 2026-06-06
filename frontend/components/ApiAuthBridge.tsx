"use client";

import { useEffect } from "react";
import { setApiAuthProvider } from "@/lib/api";
import { useDevUser, getOrCreateUserId } from "@/lib/use-dev-user";

export default function ApiAuthBridge() {
  const { userId, isSignedIn } = useDevUser();

  useEffect(() => {
    // Re-register whenever auth state resolves so the header always matches
    // the founderId used in URL params (prevents 403 on first load after sign-in).
    const resolvedId = isSignedIn ? userId : getOrCreateUserId();
    setApiAuthProvider(async () => ({ token: null, userId: resolvedId }));
    return () => setApiAuthProvider(null);
  }, [userId, isSignedIn]);

  return null;
}
