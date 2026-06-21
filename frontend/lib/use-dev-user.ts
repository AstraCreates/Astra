import { useEffect } from "react";
import { useSession } from "next-auth/react";

const DEV_USER_ID_KEY = "astra_dev_user_id";
const AUTH_USER_ID_KEY = "astra_auth_user_id";

function generateId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return "user_" + crypto.randomUUID().replace(/-/g, "").slice(0, 20);
  }
  return "user_" + Math.random().toString(36).slice(2, 12) + Math.random().toString(36).slice(2, 12);
}

function normalizeSignedInUserId(email: string): string {
  return "google_" + email.toLowerCase().replace(/[^a-z0-9]/g, "_");
}

function getPersistedUserId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_USER_ID_KEY) || localStorage.getItem(DEV_USER_ID_KEY);
}

export function getOrCreateUserId(): string {
  if (typeof window === "undefined") return "anon";
  let id = getPersistedUserId();
  if (!id) {
    id = generateId();
    localStorage.setItem(DEV_USER_ID_KEY, id);
  }
  return id;
}

export function useDevUser() {
  const { data: session, status } = useSession();

  const isLoading = status === "loading";
  const isSignedIn = status === "authenticated" && !!session?.user?.email;

  const googleEmail = session?.user?.email ?? null;
  // Keep identity stable across auth transitions and across surfaces.
  // A signed-in user should keep the same founder ID in web and desktop, and
  // a brief auth-loading phase should not mint a fresh per-device local ID.
  const signedInUserId = isSignedIn && googleEmail
    ? normalizeSignedInUserId(googleEmail)
    : null;
  const userId = signedInUserId || getOrCreateUserId();

  // Keep localStorage in sync so ApiAuthBridge always sends the right founder ID + email.
  useEffect(() => {
    if (isSignedIn && googleEmail) {
      const stableId = normalizeSignedInUserId(googleEmail);
      localStorage.setItem(AUTH_USER_ID_KEY, stableId);
      localStorage.setItem(DEV_USER_ID_KEY, stableId);
      localStorage.setItem("astra_auth_email", googleEmail);
    }
  }, [isSignedIn, googleEmail]);

  return {
    userId,
    isSignedIn,
    isLoading,
    user: {
      id: userId,
      email: googleEmail,
      fullName: session?.user?.name ?? googleEmail ?? "Dev User",
      imageUrl: session?.user?.image ?? null,
    },
  };
}
