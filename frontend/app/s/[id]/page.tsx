import { Suspense } from "react";
import SessionView from "@/components/SessionView";
import CustomAgentSessionView from "@/components/CustomAgentSessionView";
import SessionRoute from "@/components/SessionRoute";

// Server-side: use the internal Docker service URL so the fetch works from
// inside the frontend container without going through the public network.
const BACKEND = process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetchSessionMeta(sessionId: string) {
  try {
    const res = await fetch(`${BACKEND}/sessions/${encodeURIComponent(sessionId)}/meta`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return res.json() as Promise<{
      stack_id: string;
      company_name: string;
      goal: string;
      status: string;
      founder_id: string;
    }>;
  } catch {
    return null;
  }
}

export default async function SessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const meta = await fetchSessionMeta(id);

  if (meta?.stack_id === "custom") {
    const rawStatus = meta.status ?? "running";
    const initialStatus =
      rawStatus === "done" || rawStatus === "completed" ? "done"
      : rawStatus === "error" || rawStatus === "failed" ? "error"
      : "running";

    return (
      <Suspense>
        <CustomAgentSessionView
          sessionId={id}
          agentName={meta.company_name ?? ""}
          goal={meta.goal ?? ""}
          initialStatus={initialStatus}
          founderId={meta.founder_id ?? ""}
        />
      </Suspense>
    );
  }

  if (meta !== null) {
    // SSR fetch succeeded and it's a regular session
    return (
      <Suspense>
        <SessionView key={id} sessionId={id} />
      </Suspense>
    );
  }

  // SSR fetch failed (auth gated in this environment) — fall back to
  // client-side detection so custom sessions still get their dedicated view.
  return (
    <Suspense>
      <SessionRoute sessionId={id} />
    </Suspense>
  );
}
