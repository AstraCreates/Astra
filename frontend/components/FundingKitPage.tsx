"use client";

import { useEffect, useState, useCallback } from "react";
import PageHeader, { HeaderPrimaryBtn } from "@/components/PageHeader";
import { PdfEmbed } from "@/components/GoalWorkspace";
import { useCompany } from "@/lib/company-context";
import {
  getFundingStatus,
  triggerFundingGenerate,
  type FundingKitStatus,
} from "@/lib/api";

export default function FundingKitPage() {
  const { founderId, companyId } = useCompany();
  const [status, setStatus] = useState<FundingKitStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!founderId) return;
    try {
      const s = await getFundingStatus(founderId, companyId || founderId);
      setStatus(s);
    } catch {
      setError("Couldn't load funding kit status.");
    } finally {
      setLoading(false);
    }
  }, [founderId, companyId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll while generating
  useEffect(() => {
    if (!status?.generating) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [status?.generating, refresh]);

  async function handleGenerate() {
    if (!founderId) return;
    setTriggering(true);
    setError("");
    try {
      await triggerFundingGenerate(founderId, companyId || founderId);
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start generation.");
    } finally {
      setTriggering(false);
    }
  }

  const generating = status?.generating || triggering;
  const needsRefresh = status?.needs_refresh && !generating;
  const hasDocuments = (status?.documents?.length ?? 0) > 0;

  return (
    <div className="h-full flex flex-col bg-white">
      <PageHeader
        title="Funding Kit"
        subtitle="AI-generated pitch materials, always in sync with your company genome"
        actions={
          <HeaderPrimaryBtn onClick={handleGenerate} disabled={generating}>
            {generating ? "Generating…" : hasDocuments ? "Regenerate" : "Generate Kit"}
          </HeaderPrimaryBtn>
        }
      />

      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {loading && <p className="text-sm text-gray-400">Loading…</p>}

        {error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">{error}</div>
        )}

        {needsRefresh && (
          <div className="flex items-center gap-3 text-sm bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
            <span className="text-amber-600 font-semibold">⚠ Outdated</span>
            <span className="text-amber-700">Company genome changed since last generation.</span>
            <button onClick={handleGenerate} disabled={generating} className="ml-auto text-amber-700 font-semibold underline underline-offset-2 text-xs">
              Regenerate now
            </button>
          </div>
        )}

        {generating && (
          <div className="flex items-center gap-3 text-sm text-blue-600 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3">
            <span className="animate-spin inline-block">⟳</span>
            Generating funding documents — this takes about 30–60 seconds…
          </div>
        )}

        {!loading && !hasDocuments && !generating && (
          <div className="text-center py-16 text-gray-400">
            <div style={{ fontSize: 36, marginBottom: 12 }}>◈</div>
            <p className="text-sm font-medium text-gray-500 mb-1">No documents yet</p>
            <p className="text-xs text-gray-400 mb-4">
              Fill in your Company Brain, then generate your kit — Astra builds a pitch deck
              and executive summary tailored to your company.
            </p>
            <button onClick={handleGenerate} disabled={generating} className="btn pri">
              Generate Funding Kit
            </button>
          </div>
        )}

        {hasDocuments && status && (
          <div className="space-y-8">
            {status.generated_at && (
              <p className="text-xs text-gray-400">
                Last generated {new Date(status.generated_at).toLocaleString()}
                {status.needs_refresh ? " · outdated" : " · up to date"}
              </p>
            )}
            {status.documents.map((doc) => (
              <div key={doc.type} className="space-y-2">
                <div className="text-xs font-bold uppercase tracking-wide text-gray-500">{doc.label}</div>
                {doc.source_path ? (
                  <PdfEmbed path={doc.source_path} height={520} />
                ) : (
                  <p className="text-sm text-gray-400">Document not available.</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
