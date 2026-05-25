const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Task {
  id: string;
  goal_id: string;
  agent: string;
  status: "pending" | "running" | "done" | "blocked" | "awaiting_approval";
  output: Record<string, unknown> | null;
  reasoning: string | null;
  blocked_reason: string | null;
  depends_on: string[];
  created_at: string;
  updated_at: string;
}

export interface Goal {
  id: string;
  founder_id: string;
  raw_instruction: string;
  status: "running" | "done" | "blocked";
  created_at: string;
}

export interface GoalStatus {
  goal: Goal;
  tasks: Task[];
}

export interface SetupStatus {
  github: boolean;
  vercel: boolean;
  sendgrid: boolean;
  instagram: boolean;
  tiktok: boolean;
  meta_ads: boolean;
}

export interface SetupResult {
  founder_id: string;
  email: string;
  services: Record<string, unknown>;
  summary: string[];
  composio_oauth_urls?: Record<string, string>;
}

export async function submitGoal(
  founderId: string,
  instruction: string,
  constraints: Record<string, unknown> = {}
): Promise<{ session_id: string; status: string }> {
  const res = await fetch(`${BASE}/goal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, instruction, constraints }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function streamGoal(sessionId: string): EventSource {
  return new EventSource(`${BASE}/stream/${sessionId}`);
}

export async function getGoalStatus(goalId: string): Promise<GoalStatus> {
  const res = await fetch(`${BASE}/status/${goalId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function approveTask(taskId: string): Promise<void> {
  const res = await fetch(`${BASE}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId, approval_token: "founder" }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function rejectTask(taskId: string, reason: string): Promise<void> {
  const res = await fetch(`${BASE}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId, reason }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function setupAccounts(
  founderId: string,
  email: string,
  password: string
): Promise<SetupResult> {
  const res = await fetch(`${BASE}/setup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, email, password }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getSetupStatus(founderId: string): Promise<SetupStatus> {
  const res = await fetch(`${BASE}/setup/${founderId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveServiceCredential(
  founderId: string,
  service: string,
  credentials: Record<string, string>
): Promise<void> {
  const res = await fetch(`${BASE}/setup/service`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, service, credentials }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function getComposioOAuthUrls(
  founderId: string
): Promise<Record<string, string>> {
  const res = await fetch(`${BASE}/setup/composio/connect/${founderId}`);
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.oauth_urls ?? {};
}

export const AGENT_LABELS: Record<string, string> = {
  research: "Market Research",
  web: "Web & Landing Page",
  marketing: "Marketing & Social",
  technical: "Technical Architecture",
  legal: "Legal & Compliance",
  ops: "Ops & Fundraising",
};

export const AGENT_ORDER = ["research", "web", "marketing", "technical", "legal", "ops"];
