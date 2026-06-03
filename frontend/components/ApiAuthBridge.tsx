"use client";

import { useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { setApiAuthProvider } from "@/lib/api";

export default function ApiAuthBridge() {
  const { getToken, userId } = useAuth();

  useEffect(() => {
    setApiAuthProvider(async () => {
      try {
        const token = await getToken();
        return { token, userId };
      } catch {
        return { token: null, userId };
      }
    });
    return () => setApiAuthProvider(null);
  }, [getToken, userId]);

  return null;
}
