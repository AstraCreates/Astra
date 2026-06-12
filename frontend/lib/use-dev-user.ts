import { useEffect } from "react";
import { useSession } from "next-auth/react";

function generateId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return "user_" + crypto.randomUUID().replace(/-/g, "").slice(0, 20);
  }
  return "user_" + Math.random().toString(36).slice(2, 12) + Math.random().toString(36).slice(2, 12);
}

export function getOrCreateUserId(): string {
  if (typeof window === "undefined") return "anon";
  let id = localStorage.getItem("astra_dev_user_id");
  if (!id) {
    id = generateId();
    localStorage.setItem("astra_dev_user_id", id);
  }
  return id;
}

export function useDevUser() {
  const { data: session, status } = useSession();

  const isLoading = status === "loading";
  const isSignedIn = status === "authenticated" && !!session?.user?.email;

  const googleEmail = session?.user?.email ?? null;
  // Identity MUST stay stable across the auth-loading flicker. Returning a
  // transient "anon" while `status === "loading"` made the app fetch a
  // different founder's workspace (and 4403'd the terminal takeover) until
  // auth resolved. getOrCreateUserId() returns the persisted id — which the
  // effect below keeps set to google_<email> for returning signed-in users —
  // so a brief loading state no longer swaps the founder out from under us.
  const userId = isSignedIn && googleEmail
    ? "google_" + googleEmail.replace(/[^a-z0-9]/g, "_")
    : getOrCreateUserId();

  // Keep localStorage in sync so ApiAuthBridge always sends the right founder ID.
  useEffect(() => {
    if (isSignedIn && googleEmail) {
      localStorage.setItem("astra_dev_user_id", "google_" + googleEmail.replace(/[^a-z0-9]/g, "_"));
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
