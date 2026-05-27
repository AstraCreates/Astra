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
  supabase: boolean;
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

export async function continueSession(
  founderId: string,
  priorSessionId: string,
  instruction: string,
  agents?: string[]
): Promise<{ session_id: string; status: string; prior_session_id: string }> {
  const res = await fetch(`${BASE}/goal/continue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, prior_session_id: priorSessionId, instruction, agents }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
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
  research_2: "Market Research II",
  research_competitors: "Competitor Intel",
  research_competitors_2: "Competitor Intel II",
  research_execution: "Execution Strategy",
  research_execution_2: "Execution Strategy II",
  web: "Web & Landing Page",
  marketing: "Marketing & Social",
  technical: "Technical Architecture",
  legal: "Legal & Compliance",
  ops: "Ops & Fundraising",
  sales: "Sales & Outreach",
  design: "Design & Brand",
};

export const AGENT_ORDER = ["research", "research_2", "research_competitors", "research_competitors_2", "research_execution", "research_execution_2", "web", "marketing", "technical", "legal", "ops", "sales", "design"];

const AGENT_ORDER_INDEX = new Map(AGENT_ORDER.map((agent, index) => [agent, index]));

export function sortAgentsByOrder<T extends { agent: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const aIndex = AGENT_ORDER_INDEX.get(a.agent) ?? Number.MAX_SAFE_INTEGER;
    const bIndex = AGENT_ORDER_INDEX.get(b.agent) ?? Number.MAX_SAFE_INTEGER;
    if (aIndex !== bIndex) return aIndex - bIndex;
    return a.agent.localeCompare(b.agent);
  });
}

export function sortAgentNamesByOrder(agentNames: string[]): string[] {
  return [...new Set(agentNames)].sort((a, b) => {
    const aIndex = AGENT_ORDER_INDEX.get(a) ?? Number.MAX_SAFE_INTEGER;
    const bIndex = AGENT_ORDER_INDEX.get(b) ?? Number.MAX_SAFE_INTEGER;
    if (aIndex !== bIndex) return aIndex - bIndex;
    return a.localeCompare(b);
  });
}

export const TOOL_DESCRIPTIONS: Record<string, string> = {
  github_create_repo: "Creating GitHub repository",
  supabase_create_project: "Provisioning Supabase database",
  supabase_generate_schema: "Designing database schema",
  clerk_generate_integration: "Setting up authentication",
  posthog_generate_integration: "Configuring analytics",
  clarity_setup_for_app: "Adding session recording",
  claude_code_scaffold: "Building codebase with Claude Code",
  vercel_deploy_from_github: "Deploying to Vercel",
  vercel_deploy: "Deploying to Vercel",
  cloudflare_setup_vercel_domain: "Configuring Cloudflare DNS",
  generate_landing_page_html: "Generating landing page",
  deep_research: "Deep research via Gemini + Google Search",
  web_search: "Searching the web",
  search_and_read: "Searching and reading pages",
  news_search: "Searching recent news",
  obsidian_log: "Saving session notes",
  generate_pdf: "Generating PDF document",
  send_email_campaign: "Sending email campaign",
  composio_gmail_send: "Sending email",
  composio_linear_create_issue: "Creating Linear tickets",
  composio_notion_create_page: "Writing to Notion",
  resend_send_email: "Sending email via Resend",
  find_leads: "Finding leads",
  enrich_lead: "Enriching lead data",
  build_outreach_sequence: "Building outreach sequence",
  format_legal_document: "Drafting legal document",
  generate_wireframe: "Generating wireframe",
  generate_color_palette: "Generating color palette",
};
