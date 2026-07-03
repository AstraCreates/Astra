"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AgentsRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/automations?tab=agents"); }, [router]);
  return null;
}
