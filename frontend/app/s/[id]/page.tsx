import { Suspense } from "react";
import SessionView from "@/components/SessionView";

// Clean, shareable session URL: /s/<session_id> — no founder in the URL, works
// logged-out (SessionView reads the public session meta + the open event stream).
export default async function SessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <SessionView key={id} sessionId={id} />
    </Suspense>
  );
}
