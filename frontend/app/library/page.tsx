"use client";

import LibraryPanel from "@/components/LibraryPanel";
import { useDevUser } from "@/lib/use-dev-user";

export default function LibraryPage() {
  const { userId } = useDevUser();
  return <LibraryPanel founderId={userId} />;
}
