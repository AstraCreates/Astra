"use client";

import { useEffect } from "react";
import { setApiAuthProvider } from "@/lib/api";
import { getOrCreateUserId } from "@/lib/use-dev-user";

export default function ApiAuthBridge() {
  useEffect(() => {
    setApiAuthProvider(async () => {
      const userId = getOrCreateUserId();
      return { token: null, userId };
    });
    return () => setApiAuthProvider(null);
  }, []);

  return null;
}
