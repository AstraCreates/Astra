import { useEffect, useState } from "react";

function getOrCreateUserId(): string {
  if (typeof window === "undefined") return "anon";
  let id = localStorage.getItem("astra_dev_user_id");
  if (!id) {
    id = "user_" + crypto.randomUUID().replace(/-/g, "").slice(0, 20);
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
