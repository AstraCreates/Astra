"use client";

import { useEffect, useState } from "react";
import { useCompany } from "@/lib/company-context";
import { deleteSquad, friendlyErrorMessage, getCompanyHomeData, retryTask, type CompanyHomeData } from "@/lib/company-os";
import SquadGraph from "@/components/SquadGraph";
import SquadDetailPanel from "@/components/SquadDetailPanel";

const POLL_INTERVAL_MS = 3000;
const POLL_MAX_BACKOFF_MS = 60000;

export default function SquadsPage() {
  const { founderId, companyId } = useCompany();
  const [home, setHome] = useState<CompanyHomeData | null>(null);
  const [notice, setNotice] = useState("");
  const [selectedSquadId, setSelectedSquadId] = useState("");
  const [retryingTaskId, setRetryingTaskId] = useState("");
  const [deletingSquadId, setDeletingSquadId] = useState("");

  // Same sequential setTimeout-chain + exponential-backoff pattern already
  // proven in CompanyHome.tsx's main poll -- a slow/erroring backend can't
  // pile up overlapping requests, and repeated failures back off instead of
  // hammering the endpoint forever.
  useEffect(() => {
    if (!founderId || !companyId) return;
    let live = true;
    let timer = 0;
    let consecutiveFailures = 0;
    const refresh = () => {
      void getCompanyHomeData({ founderId, companyId })
        .then((data) => {
          if (!live) return;
          setHome(data);
          setNotice("");
          consecutiveFailures = 0;
          schedule(POLL_INTERVAL_MS);
        })
        .catch(() => {
          if (!live) return;
          setNotice("Squad data is ready while live updates reconnect.");
          consecutiveFailures += 1;
          schedule(Math.min(POLL_INTERVAL_MS * 2 ** consecutiveFailures, POLL_MAX_BACKOFF_MS));
        });
    };
    const schedule = (delay: number) => { if (live) timer = window.setTimeout(refresh, delay); };
    refresh();
    return () => { live = false; window.clearTimeout(timer); };
  }, [founderId, companyId]);

  useEffect(() => {
    if (!home) return;
    if (selectedSquadId && !home.squads.some(squad => squad.id === selectedSquadId)) {
      setSelectedSquadId("");
    }
  }, [home, selectedSquadId]);

  const handleRetryTask = async (taskId: string) => {
    if (!founderId || !companyId) return;
    setRetryingTaskId(taskId);
    try {
      const data = await retryTask({ founderId, companyId }, taskId);
      setHome(data);
    } catch (error) {
      setNotice(friendlyErrorMessage(error, "Could not retry that task — try again."));
    } finally {
      setRetryingTaskId("");
    }
  };

  const handleDeleteSquad = async () => {
    if (!founderId || !companyId || !selectedSquad) return;
    setDeletingSquadId(selectedSquad.id);
    try {
      await deleteSquad({ founderId, companyId }, selectedSquad.id);
      setHome(current => current ? { ...current, squads: current.squads.filter(s => s.id !== selectedSquad.id) } : null);
      setSelectedSquadId("");
    } catch (error) {
      setNotice(friendlyErrorMessage(error, "Could not delete that squad — try again."));
    } finally {
      setDeletingSquadId("");
    }
  };

  const squads = home?.squads ?? [];
  const selectedSquad = squads.find(squad => squad.id === selectedSquadId) ?? null;
  const selectedSquadArtifacts = selectedSquad ? home?.brain.artifacts.filter(artifact => artifact.initiativeId === selectedSquad.initiativeId) ?? [] : [];

  return (
    <div style={{ padding: "24px 30px", display: "grid", gap: 16, maxWidth: 1400, margin: "0 auto" }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "var(--fg)" }}>Squads</h1>
        <p style={{ margin: "4px 0 0", fontSize: 12.5, color: "var(--fm)" }}>Every squad working on the company, how they hand off to each other, and what they've decided in their meetings.</p>
        {notice && <p style={{ margin: "4px 0 0", fontSize: 11.5, color: "var(--amber)" }}>{notice}</p>}
      </div>
      {!home ? (
        <div className="empty" style={{ minHeight: 280 }}>
          <div className="empty-title">Loading squads…</div>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.4fr) minmax(320px, 1fr)", gap: 16, alignItems: "start" }}>
          <SquadGraph squads={squads} brain={home.brain} selectedSquadId={selectedSquadId} onSelectSquad={setSelectedSquadId} />
          <SquadDetailPanel
            squad={selectedSquad}
            artifacts={selectedSquadArtifacts}
            retryingTaskId={retryingTaskId}
            onRetryTask={handleRetryTask}
            onDeleteSquad={handleDeleteSquad}
          />
        </div>
      )}
    </div>
  );
}
