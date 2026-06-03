import { useEffect, useState } from "react";

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
  const [userId, setUserId] = useState<string>("anon");
  const [name, setName] = useState<string>("Dev User");
  const [image, setImage] = useState<string | null>(null);
  const [isSignedIn, setIsSignedIn] = useState(false);

  useEffect(() => {
    // Try NextAuth session first
    fetch("/api/auth/session")
      .then(r => r.json())
      .then(session => {
        if (session?.user?.email) {
          // Signed in via Google
          const uid = "google_" + session.user.email.replace(/[^a-z0-9]/g, "_");
          localStorage.setItem("astra_dev_user_id", uid);
          setUserId(uid);
          setName(session.user.name ?? session.user.email);
          setImage(session.user.image ?? null);
          setIsSignedIn(true);
        } else {
          // Not signed in — use localStorage identity
          const uid = getOrCreateUserId();
          setUserId(uid);
          setIsSignedIn(false);
        }
      })
      .catch(() => {
        const uid = getOrCreateUserId();
        setUserId(uid);
        setIsSignedIn(false);
      });
  }, []);

  return {
    userId,
    isSignedIn,
    user: { id: userId, fullName: name, imageUrl: image },
  };
}
