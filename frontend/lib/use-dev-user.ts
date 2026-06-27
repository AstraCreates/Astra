import { useEffect } from "react";
import { useSession } from "next-auth/react";

const DEV_USER_ID_KEY = "astra_dev_user_id";
const AUTH_USER_ID_KEY = "astra_auth_user_id";
const QA_BYPASS_KEY = "astra_qa_bypass";
const QA_BYPASS_USER_ID = "qa_local_user";

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

function hasQaBypassQuery(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("qa") === "1";
}

function ensureQaBypassState(): string | null {
  if (typeof window === "undefined") return null;
  if (!hasQaBypassQuery()) return null;
  localStorage.setItem(QA_BYPASS_KEY, "1");
  localStorage.setItem(AUTH_USER_ID_KEY, QA_BYPASS_USER_ID);
  localStorage.setItem(DEV_USER_ID_KEY, QA_BYPASS_USER_ID);
  return QA_BYPASS_USER_ID;
}

function isQaBypassEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return process.env.NODE_ENV !== "production" && (localStorage.getItem(QA_BYPASS_KEY) === "1" || hasQaBypassQuery());
}

export function getOrCreateUserId(): string {
  if (typeof window === "undefined") return "anon";
  const qaUserId = ensureQaBypassState();
  if (qaUserId) return qaUserId;
  let id = getPersistedUserId();
  if (!id) {
    id = generateId();
    localStorage.setItem(DEV_USER_ID_KEY, id);
  }
  return id;
}

export function useDevUser() {
  const { data: session, status } = useSession();
  const qaBypass = isQaBypassEnabled();

  const isLoading = !qaBypass && status === "loading";
  const isSignedIn = (status === "authenticated" && !!session?.user?.email) || qaBypass;

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
    if (qaBypass) {
      ensureQaBypassState();
    }
    if (isSignedIn && googleEmail) {
      const stableId = normalizeSignedInUserId(googleEmail);
      localStorage.setItem(AUTH_USER_ID_KEY, stableId);
      localStorage.setItem(DEV_USER_ID_KEY, stableId);
      localStorage.setItem("astra_auth_email", googleEmail);
    }
  }, [isSignedIn, googleEmail, qaBypass]);

  return {
    userId,
    isSignedIn,
    isLoading,
    user: {
      id: userId,
      email: googleEmail,
      fullName: session?.user?.name ?? googleEmail ?? (qaBypass ? "QA User" : "Dev User"),
      imageUrl: session?.user?.image ?? null,
    },
  };
}
