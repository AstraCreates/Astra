"use client";
import { Component, useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

class TileErrorBoundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false };
  static getDerivedStateFromError() { return { error: true }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ fontSize: 11, color: "var(--fm)", padding: "12px 8px", textAlign: "center" }}>
          Tile error
        </div>
      );
    }
    return this.props.children;
  }
}
import {
  getDashboardElements,
  removeDashboardElement,
  refreshElement,
  type DashboardElement,
} from "@/lib/dashboard-api";

import TileShell from "@/components/tiles/TileShell";
import MetricTile from "@/components/tiles/MetricTile";
import ChartTile from "@/components/tiles/ChartTile";
import TableTile from "@/components/tiles/TableTile";
import ButtonTile from "@/components/tiles/ButtonTile";
import MonitorTile from "@/components/tiles/MonitorTile";
import ProgressTile from "@/components/tiles/ProgressTile";
import MarkdownTile from "@/components/tiles/MarkdownTile";
import ListTile from "@/components/tiles/ListTile";
import StatusBoardTile from "@/components/tiles/StatusBoardTile";
import EmbedTile from "@/components/tiles/EmbedTile";

interface Props {
  founderId: string;
}

function TileContent({
  element,
  liveConfig,
}: {
  element: DashboardElement;
  liveConfig: Record<string, unknown> | null;
}) {
  const cfg = liveConfig ? { ...element.config, ...liveConfig } : element.config;
  const isBig = element.size === "big" || element.size === "xl";

  switch (element.type) {
    case "metric":
      return <MetricTile config={cfg as Parameters<typeof MetricTile>[0]["config"]} />;
    case "chart":
      return <ChartTile config={cfg as Parameters<typeof ChartTile>[0]["config"]} isBig={isBig} />;
    case "table":
      return <TableTile config={cfg as Parameters<typeof TableTile>[0]["config"]} />;
    case "button":
      return <ButtonTile config={cfg as Parameters<typeof ButtonTile>[0]["config"]} />;
    case "monitor":
      return <MonitorTile element={{ ...element, config: cfg }} />;
    case "progress":
      return <ProgressTile config={cfg as Parameters<typeof ProgressTile>[0]["config"]} />;
    case "markdown":
      return <MarkdownTile config={cfg as Parameters<typeof MarkdownTile>[0]["config"]} />;
    case "list":
      return <ListTile config={cfg as Parameters<typeof ListTile>[0]["config"]} />;
    case "status_board":
      return <StatusBoardTile config={cfg as Parameters<typeof StatusBoardTile>[0]["config"]} />;
    case "embed":
      return <EmbedTile config={cfg as Parameters<typeof EmbedTile>[0]["config"]} />;
    default:
      return <MarkdownTile config={{ content: JSON.stringify(cfg, null, 2) }} />;
  }
}

export default function DashboardCanvas({ founderId }: Props) {
  const [elements, setElements] = useState<DashboardElement[]>([]);
  const [liveConfigs, setLiveConfigs] = useState<Record<string, Record<string, unknown>>>({});
  const [refreshingIds, setRefreshingIds] = useState<Set<string>>(new Set());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    if (!founderId) return;
    try {
      const data = await getDashboardElements(founderId);
      setElements(data);
    } catch {
      // silently fail — dashboard is bonus UI, never crash parent
    }
  }, [founderId]);

  // Initial load + 30s poll
  useEffect(() => {
    load();
    pollRef.current = setInterval(load, 30_000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [load]);

  // Per-tile refresh for data_source tiles
  useEffect(() => {
    const timers: ReturnType<typeof setInterval>[] = [];
    for (const el of elements) {
      if (!el.data_source || el.refresh_interval <= 0) continue;
      const doRefresh = async () => {
        setRefreshingIds((p) => new Set(p).add(el.id));
        try {
          const updated = await refreshElement(founderId, el.id);
          setLiveConfigs((p) => ({ ...p, [el.id]: updated }));
        } catch {}
        finally {
          setRefreshingIds((p) => { const n = new Set(p); n.delete(el.id); return n; });
        }
      };
      timers.push(setInterval(doRefresh, el.refresh_interval * 1000));
    }
    return () => { timers.forEach(clearInterval); };
  }, [elements, founderId]);

  const handleRemove = async (id: string) => {
    setElements((p) => p.filter((e) => e.id !== id));
    try { await removeDashboardElement(founderId, id); } catch {}
  };

  if (!elements.length) return null;

  // Group by section
  const sections: { name: string; items: DashboardElement[] }[] = [];
  const seen = new Set<string>();
  for (const el of elements) {
    const sec = el.section ?? "";
    if (!seen.has(sec)) {
      seen.add(sec);
      sections.push({ name: sec, items: [] });
    }
    sections[sections.length - 1].items.push(el);
  }
  // Fix: sections array may have items from previous group, rebuild properly
  const grouped = new Map<string, DashboardElement[]>();
  for (const el of elements) {
    const k = el.section ?? "";
    if (!grouped.has(k)) grouped.set(k, []);
    grouped.get(k)!.push(el);
  }

  return (
    <>
      <style>{`
        @keyframes dc-pulse {
          0%, 100% { opacity: 0.5; transform: scale(1); }
          50% { opacity: 1; transform: scale(1.3); }
        }
      `}</style>
      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        {Array.from(grouped.entries()).map(([section, items]) => (
          <div key={section}>
            {section && (
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: "var(--fm)",
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  marginBottom: 10,
                  paddingLeft: 2,
                }}
              >
                {section}
              </div>
            )}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(12, 1fr)",
                gridAutoRows: "minmax(130px, auto)",
                gap: 12,
              }}
            >
              {items.map((el) => (
                <TileErrorBoundary key={el.id}>
                  <TileShell
                    element={el}
                    onRemove={handleRemove}
                    isRefreshing={refreshingIds.has(el.id)}
                  >
                    <TileContent
                      element={el}
                      liveConfig={liveConfigs[el.id] ?? null}
                    />
                  </TileShell>
                </TileErrorBoundary>
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
