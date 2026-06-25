"use client";

import { useEffect, useState } from "react";
import SessionView from "@/components/SessionView";
import CustomAgentSessionView from "@/components/CustomAgentSessionView";
import { getSessionMeta } from "@/lib/api";

type Status = "running" | "done" | "error";

function toStatus(raw: string): Status {
  if (raw === "done" || raw === "completed") return "done";
  if (raw === "error" || raw === "failed") return "error";
  return "running";
}

export default function SessionRoute({ sessionId }: { sessionId: string }) {
  const [checked, setChecked] = useState(false);
  const [isCustom, setIsCustom] = useState(false);
  const [agentName, setAgentName] = useState("");
  const [goal, setGoal] = useState("");
  const [initialStatus, setInitialStatus] = useState<Status>("running");
  const [founderId, setFounderId] = useState("");

  useEffect(() => {
    getSessionMeta(sessionId)
      .then((meta) => {
        if (meta?.stack_id === "custom") {
          setIsCustom(true);
          setAgentName(meta.company_name ?? "");
          setGoal(meta.goal ?? "");
          setInitialStatus(toStatus(meta.status ?? "running"));
          setFounderId(meta.founder_id ?? "");
        }
      })
      .catch(() => {})
      .finally(() => setChecked(true));
  }, [sessionId]);

  if (!checked) {
    // Brief loading state — show nothing rather than flashing SessionView
    // if we know this is likely a custom session (avoids jarring swap).
    return null;
  }

  if (isCustom) {
    return (
      <CustomAgentSessionView
        sessionId={sessionId}
        agentName={agentName}
        goal={goal}
        initialStatus={initialStatus}
        founderId={founderId}
      />
    );
  }

  return <SessionView key={sessionId} sessionId={sessionId} />;
}
