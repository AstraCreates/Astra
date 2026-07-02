"use client";

import { Suspense } from "react";
import LibraryPanel from "@/components/LibraryPanel";
import { useDevUser } from "@/lib/use-dev-user";

function LibraryContent() {
  const { userId } = useDevUser();
  return <LibraryPanel founderId={userId} />;
}

export default function LibraryPage() {
  return (
    <Suspense>
      <LibraryContent />
    </Suspense>
  );
}
