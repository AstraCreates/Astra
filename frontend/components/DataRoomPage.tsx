"use client";

/**
 * Auto-maintained data room: always-current view of a company's generated
 * deliverables, live revenue, and operating profile — recomputed on every
 * load instead of a stale one-time export.
 */

import { useEffect, useState } from "react";
import PageHeader from "@/components/PageHeader";
import { PdfEmbed } from "@/components/GoalWorkspace";
import { useCompany } from "@/lib/company-context";
import { getDataRoom, type DataRoom } from "@/lib/api";

export default function DataRoomPage() {
  const { founderId, companyId } = useCompany();
  const [room, setRoom] = useState<DataRoom | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!founderId) return;
    setLoading(true);
    getDataRoom(founderId, companyId || founderId)
      .then(setRoom)
      .catch(() => setRoom(null))
      .finally(() => setLoading(false));
  }, [founderId, companyId]);

  const metrics = room?.metrics;

  return (
    <div className="h-full flex flex-col bg-white">
      <PageHeader title="Data Room" subtitle="Always current — recomputed from live data on every load" />

      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {loading && <div className="text-sm text-gray-400">Loading…</div>}

        {!loading && room && (
          <>
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Sessions" value={String(room.session_count)} />
              <Stat
                label="MRR (this month)"
                value={metrics?.connected && typeof metrics.mrr === "number" ? formatCents(metrics.mrr, metrics.currency) : metrics?.connected ? "—" : "Stripe not connected"}
              />
              <Stat
                label="Total revenue"
                value={metrics?.connected && typeof metrics.total_revenue === "number" ? formatCents(metrics.total_revenue, metrics.currency) : metrics?.connected ? "—" : "Stripe not connected"}
              />
            </div>

            <div>
              <div className="text-xs font-bold uppercase tracking-wide text-gray-500 mb-2">
                Deliverables ({room.deliverables.length})
              </div>
              {room.deliverables.length === 0 ? (
                <div className="text-sm text-gray-400">No deliverables generated yet.</div>
              ) : (
                <div className="space-y-3">
                  {room.deliverables.map((d) => (
                    <div key={d.path} className="space-y-1">
                      <div className="text-xs text-gray-500">{d.name} · {d.agent}</div>
                      <PdfEmbed path={d.path} height={280} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {!loading && !room && (
          <div className="text-sm text-gray-400">Couldn't load the data room.</div>
        )}
      </div>
    </div>
  );
}

function formatCents(cents: number, currency = "usd"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: currency.toUpperCase() }).format(cents / 100);
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
      <div className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">{label}</div>
      <div className="text-lg font-bold text-gray-900">{value}</div>
    </div>
  );
}
