import { apiFetch } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type DashboardElement = {
  id: string;
  founder_id: string;
  title: string;
  type:
    | "metric"
    | "chart"
    | "table"
    | "button"
    | "monitor"
    | "progress"
    | "markdown"
    | "list"
    | "status_board"
    | "embed";
  size: "small" | "medium" | "big" | "xl";
  config: Record<string, unknown>;
  section?: string;
  order: number;
  refresh_interval: number;
  agent?: string;
  session_id?: string;
  created_at: string;
  data_source?: {
    tool: string;
    params?: Record<string, unknown>;
    field_map?: Record<string, string>;
  };
};

export async function getDashboardElements(
  founderId: string
): Promise<DashboardElement[]> {
  const res = await apiFetch(
    `${BASE}/api/dashboard/${encodeURIComponent(founderId)}`
  );
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return (data.elements as DashboardElement[]) ?? [];
}

export async function removeDashboardElement(
  founderId: string,
  elementId: string
): Promise<void> {
  const res = await apiFetch(
    `${BASE}/api/dashboard/${encodeURIComponent(founderId)}/elements/${encodeURIComponent(elementId)}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error(await res.text());
}

export async function clearDashboard(
  founderId: string,
  section?: string
): Promise<void> {
  const url = new URL(
    `${BASE}/api/dashboard/${encodeURIComponent(founderId)}/elements`
  );
  if (section) url.searchParams.set("section", section);
  const res = await apiFetch(url.toString(), { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
}

export async function refreshElement(
  founderId: string,
  elementId: string
): Promise<Record<string, unknown>> {
  const res = await apiFetch(
    `${BASE}/api/dashboard/${encodeURIComponent(founderId)}/elements/${encodeURIComponent(elementId)}/refresh`
  );
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return (data.config as Record<string, unknown>) ?? {};
}
