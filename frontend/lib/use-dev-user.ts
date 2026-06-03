import { useEffect, useState } from "react";

function generateId(): string {
  // crypto.randomUUID only works on HTTPS — fallback for HTTP
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return "user_" + crypto.randomUUID().replace(/-/g, "").slice(0, 20);
  }
  return "user_" + Math.random().toString(36).slice(2, 12) + Math.random().toString(36).slice(2, 12);
}

function getOrCreateUserId(): string {
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
  useEffect(() => {
    setUserId(getOrCreateUserId());
  }, []);
  return { userId, isSignedIn: true, user: { id: userId, fullName: "Dev User" } };
}

export { getOrCreateUserId };
