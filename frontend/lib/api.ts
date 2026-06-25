const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type ApiAuthProvider = () => Promise<{ token?: string | null; userId?: string | null } | null>;

let apiAuthProvider: ApiAuthProvider | null = null;

export function setApiAuthProvider(provider: ApiAuthProvider | null) {
  apiAuthProvider = provider;
}

async function authHeaders(): Promise<Record<string, string>> {
  try {
    if (apiAuthProvider) {
      const auth = await apiAuthProvider();
      // Prefer verified JWT Bearer — backend derives identity from token, not header
      if (auth?.token) {
        const h: Record<string, string> = { "Authorization": `Bearer ${auth.token}` };
        if (typeof window !== "undefined") {
          const email = localStorage.getItem("astra_auth_email");
          if (email) h["x-astra-email"] = email;
        }
        return h;
      }
      // Fallback: header-based identity (dev/unauthenticated only)
      if (auth?.userId) {
        const h: Record<string, string> = { "x-astra-user-id": auth.userId };
        if (typeof window !== "undefined") {
          const email = localStorage.getItem("astra_auth_email");
          if (email) h["x-astra-email"] = email;
        }
        return h;
      }
    }
    // Last resort: read from localStorage (unauthenticated / dev mode only)
    if (typeof window !== "undefined") {
      const userId = localStorage.getItem("astra_auth_user_id") || localStorage.getItem("astra_dev_user_id");
      if (userId) {
        const h: Record<string, string> = { "x-astra-user-id": userId };
        const email = localStorage.getItem("astra_auth_email");
        if (email) h["x-astra-email"] = email;
        return h;
      }
    }
  } catch {
    // ignore
  }
  return {};
}

// Sync token cache for EventSource/WebSocket URLs (can't set custom headers).
// Updated by ApiAuthBridge whenever the bearer token changes.
let _cachedAuthToken: string | null = null;
export function _setCachedAuthToken(token: string | null) { _cachedAuthToken = token; }

/** Returns the cached JWT for use in EventSource/WS URLs (?token=...). Sync — may be null on first load. */
export function getAuthToken(): string | null {
  return _cachedAuthToken;
}

// One-shot gate: resolves when ApiAuthBridge finishes its first token fetch (success or failure).
// Prevents SSE connections from firing before we know whether the user is authenticated.
let _authReadyResolve: (() => void) | null = null;
let _authResolved = false;
const _authReady = new Promise<void>((resolve) => { _authReadyResolve = resolve; });

export function _resolveAuthReady(): void {
  if (!_authResolved) {
    _authResolved = true;
    _authReadyResolve?.();
  }
}

export function waitForAuthReady(timeoutMs = 2000): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  return Promise.race([
    _authReady,
    new Promise<void>((resolve) => window.setTimeout(resolve, timeoutMs)),
  ]);
}

export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const existing = new Headers(init.headers);
  const auth = await authHeaders();
  for (const [key, value] of Object.entries(auth)) {
    if (!existing.has(key)) existing.set(key, value);
  }
  return fetch(input, { ...init, headers: existing });
}

export async function checkOk(res: Response): Promise<Response> {
  if (res.ok) return res;
  throw new Error(await res.text());
}

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

export interface AgentStackTemplate {
  stack_id: string;
  name: string;
  target_user: string;
  primary_outcome: string;
  description: string;
  input_prompts: string[];
  tasks: Array<{
    id: string;
    agent: string;
    title: string;
    instruction: string;
    depends_on: string[];
    artifacts: string[];
  }>;
  artifacts: Array<{
    key: string;
    title: string;
    owner_agent: string;
    description: string;
    required: boolean;
  }>;
  approval_gates: Array<{
    key: string;
    title: string;
    trigger: string;
    required_before: string;
    reason: string;
  }>;
  connector_requirements: Array<{
    key: string;
    label: string;
    category: string;
    purpose: string;
    required: boolean;
  }>;
  dashboard_sections: string[];
  completion_rules: string[];
}

export interface StackRecommendation {
  stack: AgentStackTemplate;
  confidence: number;
  reason: string;
  matched_signals: string[];
}

export interface StackReadiness {
  founder_id: string;
  stack_id: string;
  stack_name: string;
  ready: boolean;
  readiness_score: number;
  required_total: number;
  connected_required: number;
  missing_required: number;
  connectors: Array<{
    key: string;
    label: string;
    category: string;
    purpose: string;
    required: boolean;
    connected: boolean;
    source: string | null;
    status: "connected" | "missing_required" | "optional";
  }>;
  next_actions: string[];
}

export interface ConnectorCoverage {
  founder_id: string;
  stack_id: string;
  stack_name: string;
  required_total: number;
  ready_required: number;
  missing_required: number;
  connected_required_without_memory: number;
  coverage_score: number;
  summary: string;
  next_actions: string[];
  connectors: Array<StackReadiness["connectors"][number] & {
    brain_sources: Array<{ key: string; label: string; status: string; record_count: number }>;
    brain_record_count: number;
    brain_covered: boolean;
    coverage_status: "ready" | "connected_no_memory" | "memory_only" | "missing_required" | "optional_missing";
  }>;
}

export interface ConnectorSetupPlan {
  founder_id: string;
  stack_id: string;
  stack_name: string;
  backend_url: string;
  ready: boolean;
  required_total: number;
  missing_required: number;
  connected_needs_sync: number;
  summary: string;
  next_actions: string[];
  connectors: Array<{
    key: string;
    label: string;
    category: string;
    purpose: string;
    required: boolean;
    connected: boolean;
    credential_service: string;
    credential_aliases: string[];
    fields: Array<{ key: string; label: string; secret: boolean; required: boolean }>;
    missing_fields: string[];
    webhook: {
      supported: boolean;
      url: string;
      secret_configured: boolean;
      auth: string;
    };
    sync: {
      brain_covered: boolean;
      brain_record_count: number;
      coverage_status: string;
    };
    validation?: ConnectorValidationItem;
    setup_status: string;
    connect_endpoint: string;
    import_endpoint: string;
  }>;
}

export interface ConnectorValidationItem {
  key: string;
  label?: string;
  category?: string;
  purpose?: string;
  required: boolean;
  credential_service: string;
  credential_aliases: string[];
  credential_status: "missing" | "valid_shape" | string;
  missing_fields: string[];
  webhook: {
    supported: boolean;
    status: "not_supported" | "secured" | "missing_secret" | string;
    secret_configured: boolean;
  };
  provider: {
    status: "not_checked" | "ok" | "error" | "unsupported" | string;
    ok: boolean;
    detail?: string;
    http_status?: number;
    [key: string]: unknown;
  };
  status: "missing_credentials" | "invalid_credentials" | "provider_error" | "validated" | "locally_valid" | string;
}

export interface ConnectorValidationReport {
  founder_id: string;
  stack_id: string;
  stack_name: string;
  live: boolean;
  ready: boolean;
  required_total: number;
  validated_required: number;
  blocked_required: number;
  connectors: ConnectorValidationItem[];
  next_actions: string[];
  summary: string;
}

export interface StackOperatingPlan {
  stack_id: string;
  stack_name: string;
  company_name: string;
  goal: string;
  outcome: string;
  operator_contract: string;
  phases: Array<{
    name: string;
    objective: string;
    lanes: Array<{ lane_id: string; agent: string; title: string }>;
  }>;
  lanes: Array<{
    id: string;
    agent: string;
    title: string;
    mission: string;
    depends_on: string[];
    artifact_keys: string[];
    artifacts: Array<{ key: string; title: string; description: string; required: boolean }>;
    handoff: string;
  }>;
  connector_plan: {
    required: Array<{ key: string; label: string; category: string; purpose: string }>;
    optional: Array<{ key: string; label: string; category: string; purpose: string }>;
    setup_rule: string;
  };
  approval_policy: Array<{
    key: string;
    title: string;
    trigger: string;
    required_before: string;
    reason: string;
  }>;
  artifact_contract: Array<{
    key: string;
    title: string;
    owner_agent: string;
    description: string;
    required: boolean;
    acceptance: string;
  }>;
  cadence: Record<string, string>;
  completion_definition: string[];
  execution_contract?: StackExecutionContract;
}

export interface StackExecutionContract {
  stack_id: string;
  stack_name: string;
  north_star: string;
  milestones: Array<{ day: number; title: string; evidence: string }>;
  kpis: Array<{ key: string; label: string; target: string }>;
  quality_gates: string[];
  cadence: Record<string, string>;
  handoff_rules: string[];
  lane_contracts: Array<{
    task_id: string;
    agent: string;
    title: string;
    owns: string[];
    depends_on: string[];
    completion_evidence: string;
    handoff_to: string[];
  }>;
}

export interface AgentDepartmentManifest {
  stack_id: string;
  stack_name: string;
  company_name: string;
  goal: string;
  department_name: string;
  positioning: string;
  target_user: string;
  primary_outcome: string;
  workflow: {
    nodes: Array<{
      id: string;
      agent: string;
      title: string;
      mission: string;
      expected_outputs: Array<{ key: string; title: string; required: boolean }>;
      depends_on: string[];
    }>;
    edges: Array<{ from: string; to: string; handoff: string }>;
    critical_path: string[];
  };
  connectors: {
    required: Array<{ key: string; label: string; category: string; purpose: string; required: boolean }>;
    optional: Array<{ key: string; label: string; category: string; purpose: string; required: boolean }>;
    rule: string;
  };
  dashboards: Array<{ key: string; title: string; purpose: string }>;
  approvals: Array<{ key: string; title: string; trigger: string; required_before: string; founder_control: string }>;
  outputs: Array<{ key: string; title: string; owner_agent: string; description: string; required: boolean; acceptance: string }>;
  human_collaboration: {
    founder_role: string[];
    agent_role: string[];
    default_mode: string;
  };
  memory_policy: {
    canonical_records: string[];
    retrieval_promises: string[];
  };
  execution_contract: StackExecutionContract;
  template_quality?: {
    stack_id: string;
    stack_name: string;
    score: number;
    ready: boolean;
    checks: Array<{ key: string; ok: boolean; detail: string }>;
    gaps: Array<{ key: string; ok: boolean; detail: string }>;
    summary: string;
  };
  operating_plan: StackOperatingPlan;
}

export interface SessionDigest {
  session_id: string;
  company_name: string;
  stack_name: string;
  summary: string;
  counts: {
    planned_agents: number;
    done_agents: number;
    running_agents: number;
    ready_artifacts: number;
    outcome_events: number;
    outcome_units: number;
    triggered_approvals: number;
    pending_approvals: number;
    saferun_actions: number;
    errors: number;
    phases_done: number;
    phases_pending: number;
    phases_total: number;
  };
  done_agents: string[];
  running_agents: string[];
  ready_artifacts: Array<{ title?: string; owner_agent?: string; preview?: string }>;
  recent_outcomes: Array<{ label?: string; value?: number; unit?: string; preview?: string }>;
  approval_focus: Array<{ title?: string; status?: string; reason?: string }>;
  errors: string[];
  next_actions: string[];
}

export interface SubteamReport {
  session_id: string;
  team: string;
  agents: string[];
  summary: string;
  completed: Array<{ agent: string; summary: string }>;
  active: Array<{ agent: string; instruction: string }>;
  pending: Array<{ agent: string; instruction: string }>;
  artifacts: Array<{ title?: string; owner_agent?: string; preview?: string }>;
  outcomes: Array<{ label?: string; value?: number; unit?: string; preview?: string }>;
  approvals: Array<{ tool?: string; approval_gate?: string; reason?: string }>;
  blockers: string[];
  next_actions: string[];
}

export interface SessionAnswer {
  session_id: string;
  question: string;
  answer_type: "subteam_report" | "run_digest" | "stack_operating_plan" | "department_manifest" | "workboard";
  answer: string;
  confidence: number;
  report?: SubteamReport;
  digest?: SessionDigest;
  operating_plan?: StackOperatingPlan;
  manifest?: AgentDepartmentManifest;
  workboard?: SessionWorkboard;
}

export interface SessionWorkboard {
  session_id: string;
  stack_name: string;
  outcome: string;
  summary: string;
  counts: {
    total: number;
    queued: number;
    running: number;
    done: number;
    blocked: number;
    founder_next: number;
    agent_next: number;
  };
  pending_approvals: Array<Record<string, unknown>>;
  items: Array<{
    id: string;
    agent: string;
    owner_type: string;
    owner: string;
    title: string;
    mission: string;
    status: string;
    next_actor: "founder" | "founder_review" | "agent";
    depends_on: string[];
    expected_artifacts: Array<Record<string, unknown>>;
    ready_artifacts: Array<Record<string, unknown>>;
    outcomes: Array<Record<string, unknown>>;
    blockers: string[];
    summary: string;
  }>;
}

export interface SessionStateSnapshot {
  session_id: string;
  status: "running" | "done" | "error" | "stalled";
  company_goal?: CompanyGoal | null;
  event_count: number;
  last_event_id: number;
  stack?: AgentStackTemplate | null;
  operating_plan?: StackOperatingPlan | null;
  manifest?: AgentDepartmentManifest | null;
  execution_contract?: StackExecutionContract | null;
  company_genome?: Record<string, unknown> | null;
  agents?: Record<string, Record<string, unknown>>;
  digest?: SessionDigest | null;
  workboard?: SessionWorkboard | null;
  approval_workflow?: {
    session_id: string;
    updated_at?: string;
    requests: Array<Record<string, unknown>>;
  };
  approvals: Array<Record<string, unknown>>;
  artifacts: Array<Record<string, unknown>>;
  outcomes: Array<Record<string, unknown>>;
  saferun_actions: Array<Record<string, unknown>>;
  completion_audit?: {
    ok: boolean;
    status: string;
    summary: string;
    failed?: Array<Record<string, unknown> & { details?: Record<string, unknown> }>;
  };
  run_ledger?: Record<string, unknown> | null;
}

export interface SetupStatus {
  github: boolean;
  vercel: boolean;
  sendgrid: boolean;
  supabase: boolean;
  instagram: boolean;
  tiktok: boolean;
  meta_ads: boolean;
  linkedin?: boolean;
  notion?: boolean;
  linear?: boolean;
  klaviyo?: boolean;
  printful?: boolean;
  yelp?: boolean;
  lemonsqueezy?: boolean;
  square?: boolean;
  twilio?: boolean;
  apps?: Record<string, boolean>;
  zero_touch?: {
    ready: boolean;
    shared_inbox: {
      email: string;
      imap_configured: boolean;
      imap_auth_ok: boolean;
      imap_detail: string;
      web_password_configured: boolean;
    };
    browser_runtime: {
      headless: boolean;
      proxy_configured: boolean;
      capsolver_configured: boolean;
      anti_bot_ready: boolean;
    };
    blockers: string[];
  };
}

export interface SetupResult {
  founder_id: string;
  email: string;
  services: Record<string, unknown>;
  summary: string[];
  composio_oauth_urls?: Record<string, string>;
  stack_id?: string;
  required_only?: boolean;
  provision_plan?: {
    stack_id: string;
    services: string[];
    connectors: Array<{ key: string; label: string; required: boolean }>;
    composio_apps: string[];
    manual_connectors: string[];
    include_foundation: boolean;
    required_only: boolean;
  };
  pending_manual_connectors?: string[];
  interaction_required?: Record<string, {
    connected: false;
    app: string;
    provider: string;
    status: "interaction_required";
    requires_human: true;
    category: string;
    error: string;
    last_url?: string;
    last_state?: string;
    next_step?: string;
    resume_supported?: boolean;
  }>;
}

export interface BrainSource {
  key: string;
  label: string;
  kind: string;
  status: string;
  record_count: number;
  last_synced_at: string | null;
  notes: string;
  credential_fields?: string[];
  oauth_apps?: string[];
  setup_url?: string;
  setup_hint?: string;
  importer?: boolean;
}

export interface BrainRecord {
  id: string;
  version_id?: string;
  version?: number;
  previous_version_id?: string | null;
  source: string;
  kind: string;
  title: string;
  url: string;
  content: string;
  snippet?: string;
  canonical: boolean;
  stale_risk: string;
  status?: string;
  domain?: string;
  supersedes?: string[];
  owner_id?: string;
  visibility?: "private" | "team" | "public";
  allowed_roles?: string[];
  updated_at: string;
  metadata?: Record<string, unknown>;
  score?: number;
}

export interface BrainRelationship {
  from: string;
  to: string;
  type: string;
  strength: number;
  evidence: string[];
}

export interface GraphRagNode {
  id: string;
  founder_id: string;
  name: string;
  type: string;
  description: string;
  importance: number;
  community_id?: string | null;
}

export interface GraphRagEdge {
  id: string;
  founder_id: string;
  source: string;
  target: string;
  relation: string;
  weight: number;
}

export interface GraphRagVisualization {
  ok: boolean;
  founder_id: string;
  nodes: GraphRagNode[];
  edges: GraphRagEdge[];
}

export interface GraphRagSyncResult {
  ok: boolean;
  founder_id: string;
  record_count: number;
  inserted_chunks: number;
  node_count: number;
  edge_count: number;
  community_count: number;
  snapshot_path: string;
}

export interface BrainProposal {
  id: string;
  kind: string;
  title: string;
  status: "open" | "resolved" | "dismissed";
  record_ids: string[];
  reason: string;
  suggested_update: string;
  created_at: string;
  updated_at?: string;
}

export interface BrainMaintenance {
  last_checked_at: string | null;
  stale_count: number;
  contradiction_count: number;
  missing_canonical_count: number;
}

export interface BrainSyncState {
  enabled: boolean;
  interval_minutes: number;
  sources: string[];
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string;
  last_error: string;
  history: Array<Record<string, unknown>>;
}

export interface BrainSchedulerState {
  running: boolean;
  interval_seconds: number;
  last_tick_at: string | null;
  last_result: Record<string, unknown> | null;
  last_error: string;
}

export interface PlatformStatus {
  status: "healthy" | "degraded";
  ready: boolean;
  started_at: number;
  now: number;
  uptime_seconds: number;
  checks: Record<string, {
    ok: boolean;
    status?: string;
    detail?: string;
    [key: string]: unknown;
  }>;
  state: {
    sessions_active: number;
    sessions_completed: number;
    events_buffered: number;
    workflow_snapshots: number;
    approval_ledgers: number;
    company_brains: number;
  };
  release: {
    pid: number;
    cwd: string;
  };
}

export interface DeployEvidenceCheck {
  key: string;
  ok: boolean;
  message: string;
  details?: Record<string, unknown>;
  missing?: string[];
}

export interface DeployEvidenceReport {
  ok: boolean;
  strict: boolean;
  founder_id: string;
  stack_id: string;
  live_connectors: boolean;
  checks: DeployEvidenceCheck[];
  failed: DeployEvidenceCheck[];
  missing: string[];
  summary: string;
}

export interface ProductionVerificationReport {
  id: string;
  ok: boolean;
  created_at: string;
  founder_id: string;
  stack_id: string;
  base_url: string;
  live_connectors: boolean;
  summary: string;
  missing: string[];
  next_actions: string[];
  verification_command: string;
  deploy_evidence: DeployEvidenceReport;
  smoke: {
    ok: boolean;
    summary: string;
    failed_count?: number;
    checks?: Array<Record<string, unknown>>;
  };
  paths?: {
    json?: string;
    markdown?: string;
    manifest?: string;
    latest_json?: string;
    latest_markdown?: string;
    latest_manifest?: string;
  };
}

export interface ProductionVerificationReports {
  reports: ProductionVerificationReport[];
  report_count: number;
  latest: ProductionVerificationReport | null;
  latest_ok: boolean;
}

export interface ProductionVerificationManifestCheck {
  key: string;
  ok: boolean;
  path: string;
  error?: string;
  expected_sha256?: string;
  actual_sha256?: string;
  expected_bytes?: number;
  actual_bytes?: number;
}

export interface ProductionVerificationManifestVerification {
  ok: boolean;
  found: boolean;
  verified: boolean;
  report_id: string;
  manifest?: Record<string, unknown>;
  checks: ProductionVerificationManifestCheck[];
  failed: ProductionVerificationManifestCheck[];
  summary: string;
}

export interface ProductionRequirements {
  ok: boolean;
  founder_id: string;
  stack_id: string;
  stack_name: string;
  base_url: string;
  environment: Array<{
    key: string;
    description: string;
    required: boolean;
    configured: boolean;
    current: string;
  }>;
  connectors: Array<{
    key: string;
    label: string;
    category: string;
    purpose: string;
    required: boolean;
    credential_fields: Array<{ key: string; required: boolean }>;
    live_validation_required: boolean;
  }>;
  required_connector_keys: string[];
  objective_evidence: ObjectiveEvidenceMatrix;
  final_gate: {
    command: string;
    admin_endpoint: string;
    requires_live_connectors: boolean;
    writes: string[];
    verify_manifest_endpoint?: string;
    bundle_endpoint?: string;
  };
  missing: string[];
  summary: string;
}

export interface ObjectiveEvidenceMatrix {
  ok: boolean;
  code_contract_ready: boolean;
  production_proven: boolean;
  founder_id: string;
  stack_id: string;
  base_url: string;
  requirements: Array<{
    key: string;
    requirement: string;
    evidence: string[];
    checks: string[];
    code_ok: boolean;
    needs_live_proof: boolean;
    production_verified: boolean;
    status: "production_verified" | "needs_live_proof" | "code_ready" | "missing_code_evidence" | string;
  }>;
  failed_code: Array<Record<string, unknown>>;
  live_proof: {
    ok: boolean;
    report_found?: boolean;
    report_ok?: boolean;
    live_connectors?: boolean;
    manifest_verified?: boolean;
    report_id?: string;
    error?: string;
  };
  live_missing: Array<{
    key: string;
    requirement: string;
    status: string;
  }>;
  summary: string;
}

export interface LaunchReadiness {
  ok: boolean;
  founder_id: string;
  stack_id: string;
  base_url: string;
  report_id: string;
  checks: Array<{
    key: string;
    ok: boolean;
    message: string;
    details?: Record<string, unknown>;
  }>;
  failed: Array<{
    key: string;
    ok: boolean;
    message: string;
    details?: Record<string, unknown>;
  }>;
  summary: string;
}

export interface ProductionLaunchResult {
  ok: boolean;
  founder_id: string;
  stack_id: string;
  base_url: string;
  report_id: string;
  verification: ProductionVerificationReport;
  manifest: ProductionVerificationManifestVerification;
  bundle: {
    ok: boolean;
    found: boolean;
    report_id: string;
    path?: string;
    filename?: string;
    bytes?: number;
    sha256?: string;
    manifest_verified?: boolean;
    summary: string;
  };
  launch_readiness: LaunchReadiness;
  summary: string;
}

export interface ProductionLaunchProofResponse {
  ok: boolean;
  found: boolean;
  proof?: ProductionLaunchResult & {
    id: string;
    created_at: string;
    paths?: {
      json?: string;
      latest_json?: string;
    };
  };
  proof_id?: string;
  error?: string;
}

export interface OrganizationAccount {
  org_id: string;
  name: string;
  owner_id: string;
  created_at: string;
  updated_at: string;
  members: Record<string, { user_id: string; role: string; status: string; joined_at?: string; updated_at?: string }>;
  subscription: {
    plan: string;
    status: string;
    stripe_customer_id: string;
    stripe_subscription_id: string;
    current_period_end: string | null;
  };
  usage: {
    period: string;
    runs: number;
    connector_syncs: number;
    approval_decisions: number;
  };
  admin_controls: {
    require_approval_for_public_actions: boolean;
    require_approval_for_billing_actions: boolean;
    allow_agent_external_writes: boolean;
    allowed_connectors: string[];
  };
  entitlements: {
    plan_id: string;
    name: string;
    monthly_runs: number;
    team_seats: number;
    connector_syncs_per_day: number;
    approval_workflows: boolean;
    company_brain: boolean;
    remaining_runs: number;
    remaining_connector_syncs: number;
    remaining_team_seats: number;
  };
  audit_log: Array<{ at: string; actor_id: string; action: string; payload: Record<string, unknown> }>;
}

export interface BillingConfigStatus {
  stripe_configured: boolean;
  portal_available: boolean;
  checkout_available: boolean;
  missing_price_ids: string[];
  plans: Record<string, {
    name: string;
    monthly_runs: number;
    team_seats: number;
    connector_syncs_per_day: number;
    approval_workflows: boolean;
    company_brain: boolean;
    price_configured: boolean;
    self_serve: boolean;
  }>;
}

export interface BillingSessionResult {
  ok: boolean;
  kind?: "checkout" | "portal";
  plan?: string;
  url?: string;
  session_id?: string;
  customer_id?: string;
  setup_required?: boolean;
  error?: string;
}

export interface BrainAnswerCitation {
  index: number;
  record_id: string;
  title: string;
  source: string;
  url?: string;
  canonical: boolean;
  score: number;
}

export interface CompanyBrain {
  founder_id: string;
  company_id?: string;
  updated_at: string;
  sources: Record<string, BrainSource>;
  records: BrainRecord[];
  relationships: BrainRelationship[];
  proposals: BrainProposal[];
  maintenance: BrainMaintenance;
  sync: BrainSyncState;
  access_control?: {
    owner_id: string;
    roles: Record<string, string>;
    role_permissions: Record<string, string[]>;
  };
}

export interface CompanySubteamReport {
  founder_id: string;
  team: string;
  agents: string[];
  window_days: number;
  record_count: number;
  session_count: number;
  by_kind: Record<string, number>;
  by_source: Record<string, number>;
  summary: string;
  highlights: Array<{
    id?: string;
    title?: string;
    source?: string;
    kind?: string;
    updated_at?: string;
    snippet?: string;
    canonical?: boolean;
  }>;
  next_actions: string[];
}

export async function submitGoal(
  founderId: string,
  instruction: string,
  constraints: Record<string, unknown> = {},
  stackId = "idea_to_revenue",
): Promise<{ session_id: string; status: string; workspace_id: string; chapter_id: string }> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 30_000);
  let res: Response;
  try {
    res = await fetch(`${BASE}/goal`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-astra-user-id": founderId },
      body: JSON.stringify({
        founder_id: founderId,
        instruction,
        constraints,
        stack_id: stackId,
      }),
      signal: ctrl.signal,
    });
  } catch (e) {
    if (ctrl.signal.aborted) throw new Error(`Request timed out reaching the backend at ${BASE}/goal. Hard-refresh (Cmd+Shift+R) and try again.`);
    throw new Error(`Could not reach the backend at ${BASE}/goal: ${e instanceof Error ? e.message : String(e)}`);
  } finally {
    clearTimeout(timer);
  }
  await checkOk(res);
  return res.json();
}

// ── Workspace API ───────────────────────────────────────────────────────────

export interface WorkspaceChapter {
  chapter_id: string;
  workspace_id: string;
  session_id: string;
  name: string;
  phase_scope: string | null;
  status: "running" | "done" | "error" | "killed";
  artifact_count: number;
  created_at: string;
  completed_at: string | null;
}

export interface WorkspaceVaultEntry {
  key: string;
  title: string;
  current: {
    chapter_id: string;
    session_id: string;
    agent: string;
    title: string;
    preview: string;
    content: string;
    updated_at: string;
  };
  history: WorkspaceVaultEntry["current"][];
}

export interface Workspace {
  workspace_id: string;
  company_id?: string;
  founder_id: string;
  name: string;
  goal: string;
  company_name: string;
  stack_id: string;
  status: string;
  created_at: string;
  last_active: string;
  chapter_ids: string[];
  chapters?: WorkspaceChapter[];
  vault?: Record<string, WorkspaceVaultEntry>;
}

export async function createWorkspace(
  founderId: string,
  name: string,
  goal: string,
  stackId: string = "idea_to_revenue",
): Promise<Workspace> {
  const res = await apiFetch(`${BASE}/workspaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, name, goal, stack_id: stackId }),
  });
  await checkOk(res);
  return res.json();
}

export async function listWorkspaces(founderId: string): Promise<Workspace[]> {
  const res = await apiFetch(`${BASE}/workspaces?founder_id=${encodeURIComponent(founderId)}`);
  await checkOk(res);
  return res.json();
}

export async function getWorkspace(workspaceId: string): Promise<Workspace> {
  const res = await apiFetch(`${BASE}/workspaces/${encodeURIComponent(workspaceId)}`);
  await checkOk(res);
  return res.json();
}

export async function updateWorkspace(workspaceId: string, fields: Partial<Pick<Workspace, "name" | "company_name" | "status">>): Promise<void> {
  await apiFetch(`${BASE}/workspaces/${encodeURIComponent(workspaceId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
}

export async function getWorkspaceVault(workspaceId: string): Promise<Record<string, WorkspaceVaultEntry>> {
  const res = await apiFetch(`${BASE}/workspaces/${encodeURIComponent(workspaceId)}/vault`);
  await checkOk(res);
  return res.json();
}

export interface AgentCatalogEntry {
  id: string;
  name: string;
  description: string;
  produces: string[];
  depends_on: string[];
}

export async function getAgentCatalog(): Promise<AgentCatalogEntry[]> {
  const res = await apiFetch(`${BASE}/agents/catalog`);
  await checkOk(res);
  const data = await res.json();
  return data.agents ?? [];
}

export async function getStacks(): Promise<AgentStackTemplate[]> {
  const res = await apiFetch(`${BASE}/stacks`);
  await checkOk(res);
  const data = await res.json();
  return data.stacks ?? [];
}

export async function getCustomStackPackage(
  agents: string[],
  instruction: string,
  founderId: string,
  companyName = ""
): Promise<AgentStackTemplate> {
  const res = await apiFetch(`${BASE}/stacks/custom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agents, instruction, founder_id: founderId, company_name: companyName }),
  });
  await checkOk(res);
  return res.json();
}

export async function recommendStack(instruction: string, companyStage?: string): Promise<StackRecommendation> {
  const res = await apiFetch(`${BASE}/stacks/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction, company_stage: companyStage }),
  });
  await checkOk(res);
  return res.json();
}

export async function getStackReadiness(founderId: string, stackId: string): Promise<StackReadiness> {
  const res = await apiFetch(`${BASE}/stacks/${encodeURIComponent(stackId)}/readiness/${encodeURIComponent(founderId)}`);
  await checkOk(res);
  return res.json();
}

export async function getConnectorCoverage(founderId: string, stackId: string): Promise<ConnectorCoverage> {
  const res = await apiFetch(`${BASE}/stacks/${encodeURIComponent(stackId)}/connector-coverage/${encodeURIComponent(founderId)}`);
  await checkOk(res);
  return res.json();
}

export async function getConnectorSetup(founderId: string, stackId: string): Promise<ConnectorSetupPlan> {
  const res = await apiFetch(`${BASE}/stacks/${encodeURIComponent(stackId)}/connector-setup/${encodeURIComponent(founderId)}`);
  await checkOk(res);
  return res.json();
}

export async function getConnectorValidation(founderId: string, stackId: string, live = false): Promise<ConnectorValidationReport> {
  const suffix = live ? "?live=true" : "";
  const res = await apiFetch(`${BASE}/stacks/${encodeURIComponent(stackId)}/connector-validation/${encodeURIComponent(founderId)}${suffix}`);
  await checkOk(res);
  return res.json();
}

export async function getStackOperatingPlan(stackId: string, goal = "", companyName = ""): Promise<StackOperatingPlan> {
  const params = new URLSearchParams();
  if (goal) params.set("goal", goal);
  if (companyName) params.set("company_name", companyName);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const res = await apiFetch(`${BASE}/stacks/${encodeURIComponent(stackId)}/operating-plan${suffix}`);
  await checkOk(res);
  return res.json();
}

export async function getStackManifest(stackId: string, goal = "", companyName = ""): Promise<AgentDepartmentManifest> {
  const params = new URLSearchParams();
  if (goal) params.set("goal", goal);
  if (companyName) params.set("company_name", companyName);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const res = await apiFetch(`${BASE}/stacks/${encodeURIComponent(stackId)}/manifest${suffix}`);
  await checkOk(res);
  return res.json();
}

export type StreamEventMessage = {
  data: string;
  lastEventId: string;
  type: string;
};

export type StreamMessageHandler = (event: StreamEventMessage) => void;
export type StreamErrorHandler = (error: unknown) => void;
export type StreamOpenHandler = () => void;

export type StreamSubscription = {
  onopen: StreamOpenHandler | null;
  onmessage: StreamMessageHandler | null;
  onerror: StreamErrorHandler | null;
  close(): void;
};

function parseEventStreamChunk(
  rawEvent: string,
  lastEventIdRef: { value: string },
): StreamEventMessage | null {
  const lines = rawEvent.split(/\r?\n/);
  let data = "";
  let eventType = "message";
  let nextLastEventId = lastEventIdRef.value;
  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    const idx = line.indexOf(":");
    const field = idx === -1 ? line : line.slice(0, idx);
    const value = idx === -1 ? "" : line.slice(idx + 1).replace(/^ /, "");
    if (field === "data") {
      data += (data ? "\n" : "") + value;
    } else if (field === "event" && value) {
      eventType = value;
    } else if (field === "id") {
      nextLastEventId = value;
    }
  }
  if (!data) return null;
  lastEventIdRef.value = nextLastEventId;
  return { data, lastEventId: nextLastEventId, type: eventType };
}

export function openEventStream(
  url: string,
  options: { lastEventId?: string | number; reconnectDelayMs?: number } = {},
): StreamSubscription {
  const aborter = new AbortController();
  const reconnectDelayMs = options.reconnectDelayMs ?? 1500;
  const lastEventIdRef = { value: options.lastEventId == null ? "" : String(options.lastEventId) };
  let closed = false;
  let authRetries = 0;
  const subscription: StreamSubscription = {
    onopen: null,
    onmessage: null,
    onerror: null,
    close() {
      closed = true;
      aborter.abort();
    },
  };

  const connect = async () => {
    let firstConnect = true;
    while (!closed) {
      try {
        if (firstConnect) {
          firstConnect = false;
          await waitForAuthReady(2000);
        }
        const headers = new Headers(await authHeaders());
        headers.set("Accept", "text/event-stream");
        if (lastEventIdRef.value && lastEventIdRef.value !== "0") headers.set("Last-Event-ID", lastEventIdRef.value);
        const res = await fetch(url, {
          method: "GET",
          headers,
          signal: aborter.signal,
          cache: "no-store",
        });
        if (!res.ok) {
          const detail = await res.text().catch(() => "");
          const err = new Error(detail || `Stream failed (${res.status})`);
          if (res.status === 401 || res.status === 403) {
            // Auth may not be ready yet (race with ApiAuthBridge token fetch).
            // Retry a few times before giving up permanently.
            if (authRetries < 4) {
              authRetries++;
              await new Promise((resolve) => window.setTimeout(resolve, authRetries * 800));
              continue;
            }
            subscription.onerror?.(err);
            return;
          }
          authRetries = 0;
          throw err;
        }
        authRetries = 0;
        if (!res.body) throw new Error("Stream body missing");
        subscription.onopen?.();
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!closed) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split(/\n\n/);
          buffer = events.pop() ?? "";
          for (const rawEvent of events) {
            const parsed = parseEventStreamChunk(rawEvent, lastEventIdRef);
            if (parsed) subscription.onmessage?.(parsed);
          }
        }
        if (closed || aborter.signal.aborted) return;
        subscription.onerror?.(new Error("Event stream disconnected"));
      } catch (error) {
        if (closed || aborter.signal.aborted) return;
        subscription.onerror?.(error);
        await new Promise((resolve) => window.setTimeout(resolve, reconnectDelayMs));
        continue;
      }
    }
  };

  void connect();
  return subscription;
}

export function streamGoal(sessionId: string): StreamSubscription {
  return openEventStream(`${BASE}/stream/${sessionId}`);
}

export interface SessionIndexEntry {
  session_id: string;
  founder_id: string;
  goal: string;
  stack_id: string;
  status: "running" | "done" | "error" | "stalled" | string;
  created_at: string;
  completed_at: string | null;
  parent_session_id?: string;
  kind?: string;
  company_name?: string;
}

export interface SessionMeta {
  session_id: string;
  founder_id: string;
  goal: string;
  company_name: string;
  stack_id: string;
  status: string;
  created_at: string;
  parent_session_id: string;
  kind: string;
  credits_used?: number;
  headroom_tokens_saved?: number;
  headroom_tokens_before?: number;
}

/** Public, unauthenticated session header — lets /s/<id> links work without the
 *  founder in the URL or being logged in. */
export async function getSessionMeta(sessionId: string): Promise<SessionMeta | null> {
  const res = await apiFetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}/meta`);
  if (!res.ok) return null;
  return res.json();
}

/** List a founder's sessions, optionally scoped to a single company/workspace. */
export async function listSessions(founderId: string, limit = 50): Promise<SessionIndexEntry[]> {
  const params = new URLSearchParams({ founder_id: founderId, limit: String(limit) });
  const res = await apiFetch(`${BASE}/sessions?${params.toString()}`);
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data?.sessions) ? data.sessions : [];
}

/** Upload a file (text/PDF/image) to be converted into agent-readable text and
 *  optionally persisted in the founder's Library. */
export async function ingestAttachment(
  founderId: string,
  file: File,
  persist = true,
): Promise<{ filename: string; content: string; truncated: boolean; kind: string; error?: string; library_id?: string }> {
  const buf = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < buf.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, Array.from(buf.subarray(i, i + CHUNK)));
  }
  const b64 = btoa(binary);
  const res = await apiFetch(`${BASE}/attachments/ingest/${encodeURIComponent(founderId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, mime: file.type, data_base64: b64, persist }),
  });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    return { filename: file.name, content: "", truncated: false, kind: "error", error: t || `Upload failed (HTTP ${res.status})` };
  }
  return res.json();
}

/** Immediately stop a running session (kill switch). */
export async function killSession(sessionId: string): Promise<boolean> {
  try {
    const res = await apiFetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}/kill`, { method: "POST" });
    return res.ok;
  } catch {
    return false;
  }
}

/** Permanently delete a session server-side so the removal syncs across devices. */
export async function deleteSessionRemote(sessionId: string): Promise<boolean> {
  try {
    const res = await apiFetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    return res.ok;
  } catch {
    return false;
  }
}

/** Emails a generated deliverable (PDF/TXT) to the founder's own connected Gmail address. */
export async function emailDeliverable(founderId: string, filename: string, label = ""): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await apiFetch(`${BASE}/founders/${encodeURIComponent(founderId)}/deliverables/email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, label }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      return { ok: false, error: detail.detail || `Failed (${res.status})` };
    }
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export type SessionImages = { logos: Record<string, string>; brand_images: { base64: string; prompt?: string }[] };
export async function getSessionImages(sessionId: string): Promise<SessionImages> {
  try {
    const res = await apiFetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}/images`);
    if (!res.ok) return { logos: {}, brand_images: [] };
    return await res.json();
  } catch {
    return { logos: {}, brand_images: [] };
  }
}

export async function getSessionDigest(sessionId: string): Promise<SessionDigest> {
  const res = await apiFetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}/digest`);
  await checkOk(res);
  return res.json();
}

export async function getSubteamReport(sessionId: string, team = "engineering"): Promise<SubteamReport> {
  const res = await apiFetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}/subteam-report?team=${encodeURIComponent(team)}`);
  await checkOk(res);
  return res.json();
}

export async function getSessionWorkboard(sessionId: string): Promise<SessionWorkboard> {
  const res = await apiFetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}/workboard`);
  await checkOk(res);
  return res.json();
}

export async function getSessionState(sessionId: string): Promise<SessionStateSnapshot> {
  const res = await apiFetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}/state`);
  await checkOk(res);
  return res.json();
}

export interface SessionBenchmark {
  available: boolean;
  sample_size: number;
  avg_outcome_count?: number;
  avg_artifact_count?: number;
  your_outcome_count?: number;
  percentile?: number;
}

export async function getSessionBenchmark(sessionId: string, founderId: string): Promise<SessionBenchmark> {
  const res = await apiFetch(`${BASE}/insights/benchmark/${encodeURIComponent(sessionId)}?founder_id=${encodeURIComponent(founderId)}`);
  await checkOk(res);
  return res.json();
}


export async function respondWebTask(taskId: string, fields: Record<string, string>): Promise<{ ok: boolean }> {
  const res = await apiFetch(`${BASE}/web-navigator/respond/${encodeURIComponent(taskId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields }),
  });
  await checkOk(res);
  return res.json();
}

export async function askSession(sessionId: string, question: string, founderId?: string): Promise<SessionAnswer> {
  const res = await apiFetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, founder_id: founderId }),
  });
  await checkOk(res);
  return res.json();
}

export async function continueSession(
  founderId: string,
  priorSessionId: string,
  instruction: string,
  agents?: string[]
): Promise<{ session_id: string; status: string; prior_session_id: string }> {
  const res = await apiFetch(`${BASE}/goal/continue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, prior_session_id: priorSessionId, instruction, agents }),
  });
  await checkOk(res);
  return res.json();
}

export async function getGoalStatus(goalId: string): Promise<GoalStatus> {
  const res = await apiFetch(`${BASE}/status/${goalId}`);
  await checkOk(res);
  return res.json();
}

export async function approveTask(taskId: string): Promise<void> {
  const res = await apiFetch(`${BASE}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId }),
  });
  await checkOk(res);
}

export async function rejectTask(taskId: string, reason: string): Promise<void> {
  const res = await apiFetch(`${BASE}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId, reason }),
  });
  await checkOk(res);
}

export async function decideStackApproval(
  sessionId: string,
  gateKey: string,
  decision: "approved" | "skipped",
  founderId?: string,
  note?: string
): Promise<void> {
  const res = await apiFetch(`${BASE}/stack/approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, gate_key: gateKey, decision, founder_id: founderId, note }),
  });
  await checkOk(res);
}

export async function setupAccounts(
  founderId: string,
  email: string,
  password: string,
  stackId = "",
  requiredOnly = true
): Promise<SetupResult> {
  const res = await apiFetch(`${BASE}/setup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      founder_id: founderId,
      email,
      password,
      stack_id: stackId,
      required_only: requiredOnly,
      include_foundation: true,
    }),
  });
  await checkOk(res);
  return res.json();
}

export async function getSetupStatus(founderId: string): Promise<SetupStatus> {
  const res = await apiFetch(`${BASE}/setup/${founderId}`);
  await checkOk(res);
  return res.json();
}

export async function saveServiceCredential(
  founderId: string,
  service: string,
  credentials: Record<string, string>
): Promise<void> {
  const res = await apiFetch(`${BASE}/setup/service`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, service, credentials }),
  });
  await checkOk(res);
}

export async function getComposioOAuthUrls(
  founderId: string
): Promise<Record<string, string>> {
  const res = await apiFetch(`${BASE}/setup/composio/connect/${founderId}`);
  await checkOk(res);
  const data = await res.json();
  return data.oauth_urls ?? {};
}

export async function getCompanyBrain(founderId: string, viewerId = "", companyId = ""): Promise<CompanyBrain> {
  const params = new URLSearchParams();
  if (viewerId) params.set("viewer_id", viewerId);
  if (companyId) params.set("company_id", companyId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}${suffix}`);
  await checkOk(res);
  return res.json();
}

export async function syncCompanyBrain(
  founderId: string,
  sources?: string[],
  companyId = ""
): Promise<{ ok: boolean; record_count: number; relationship_count: number; changed_records: number; sources: BrainSource[] }> {
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sources, company_id: companyId }),
  });
  await checkOk(res);
  return res.json();
}

export async function importCompanyBrainSources(
  founderId: string,
  sources?: string[],
  limit = 20,
  companyId = ""
): Promise<{ ok: boolean; founder_id: string; results: Array<{ ok: boolean; source: string; error?: string; ingested?: number; changed_records?: number }>; imported_sources: string[]; failed_sources: string[] }> {
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sources, limit, company_id: companyId }),
  });
  await checkOk(res);
  return res.json();
}

export async function syncGraphRag(
  founderId: string,
  companyId = ""
): Promise<GraphRagSyncResult> {
  const params = new URLSearchParams();
  if (companyId) params.set("company_id", companyId);
  const suffix = params.toString() ? `?${params}` : "";
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/graph-sync${suffix}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  await checkOk(res);
  return res.json();
}

export async function getGraphRagVisualization(
  founderId: string,
  companyId = ""
): Promise<GraphRagVisualization> {
  const params = new URLSearchParams();
  if (companyId) params.set("company_id", companyId);
  const suffix = params.toString() ? `?${params}` : "";
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/graph-rag${suffix}`);
  await checkOk(res);
  return res.json();
}

export async function getCompanyBrainAgentContext(
  founderId: string,
  query: string,
  limit = 8,
  viewerId = "",
  companyId = ""
): Promise<{ ok: boolean; context: string; records: BrainRecord[]; relationships: BrainRelationship[]; canonical_sources: BrainRecord[]; open_proposals: BrainProposal[]; sync: BrainSyncState }> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  if (viewerId) params.set("viewer_id", viewerId);
  if (companyId) params.set("company_id", companyId);
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/agent-context?${params}`);
  await checkOk(res);
  return res.json();
}

export async function askCompanyBrain(
  founderId: string,
  question: string,
  limit = 8,
  companyId = ""
): Promise<{ ok: boolean; question: string; answer: string; confidence: number; citations: BrainAnswerCitation[]; evidence: string[]; context: string }> {
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, limit, company_id: companyId }),
  });
  await checkOk(res);
  return res.json();
}

export async function getCompanySubteamReport(founderId: string, team = "engineering", days = 7): Promise<CompanySubteamReport> {
  const params = new URLSearchParams({ team, days: String(days) });
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/subteam-report?${params}`);
  await checkOk(res);
  return res.json();
}

export async function configureCompanyBrainSync(
  founderId: string,
  config: { enabled: boolean; sources?: string[]; interval_minutes?: number },
  companyId = ""
): Promise<{ ok: boolean; sync: BrainSyncState }> {
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/sync/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...config, company_id: companyId }),
  });
  await checkOk(res);
  return res.json();
}

export async function runCompanyBrainSync(
  founderId: string,
  sources?: string[],
  companyId = ""
): Promise<{ ok: boolean; skipped: boolean; sync: BrainSyncState }> {
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/sync/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sources, company_id: companyId }),
  });
  await checkOk(res);
  return res.json();
}

export async function getCompanyBrainSchedulerStatus(): Promise<{ ok: boolean; scheduler: BrainSchedulerState }> {
  const res = await apiFetch(`${BASE}/brain/scheduler/status`);
  await checkOk(res);
  return res.json();
}

export async function searchCompanyBrain(
  founderId: string,
  query: string,
  limit = 8,
  viewerId = "",
  companyId = ""
): Promise<{ query: string; count: number; results: BrainRecord[]; formatted: string }> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  if (viewerId) params.set("viewer_id", viewerId);
  if (companyId) params.set("company_id", companyId);
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/search?${params}`);
  await checkOk(res);
  return res.json();
}

export async function addCompanyBrainRecord(
  founderId: string,
  record: { source: string; title: string; content: string; kind?: string; url?: string; canonical?: boolean; stale_risk?: string; owner_id?: string; visibility?: string; allowed_roles?: string[] },
  companyId = ""
): Promise<{ ok: boolean; record: BrainRecord }> {
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/records`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...record, company_id: companyId }),
  });
  await checkOk(res);
  return res.json();
}

export async function reviseCompanyBrainRecord(
  founderId: string,
  recordId: string,
  revision: { title?: string; content?: string; canonical?: boolean; stale_risk?: string; editor_id?: string },
  companyId = ""
): Promise<{ ok: boolean; record?: BrainRecord; previous_record?: BrainRecord; error?: string }> {
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/records/${encodeURIComponent(recordId)}/revise`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...revision, company_id: companyId }),
  });
  await checkOk(res);
  return res.json();
}

export async function configureCompanyBrainAccess(
  founderId: string,
  body: { roles?: Record<string, string>; role_permissions?: Record<string, string[]> },
  companyId = ""
): Promise<{ ok: boolean; access_control: NonNullable<CompanyBrain["access_control"]> }> {
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/access`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, company_id: companyId }),
  });
  await checkOk(res);
  return res.json();
}

export async function ingestCompanyBrainRecords(
  founderId: string,
  source: string,
  records: Array<Record<string, unknown>>,
  companyId = ""
): Promise<{ ok: boolean; source: string; ingested: number; changed_records: number; record_count: number; proposal_count: number }> {
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, records, company_id: companyId }),
  });
  await checkOk(res);
  return res.json();
}

export async function maintainCompanyBrain(
  founderId: string,
  companyId = ""
): Promise<{ ok: boolean; maintenance: BrainMaintenance; proposals: BrainProposal[] }> {
  const params = new URLSearchParams();
  if (companyId) params.set("company_id", companyId);
  const suffix = params.toString() ? `?${params}` : "";
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/maintain${suffix}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  await checkOk(res);
  return res.json();
}

export async function updateBrainProposal(
  founderId: string,
  proposalId: string,
  status: "open" | "resolved" | "dismissed",
  companyId = ""
): Promise<{ ok: boolean; proposal?: BrainProposal; error?: string }> {
  const res = await apiFetch(`${BASE}/brain/${encodeURIComponent(founderId)}/proposals/${encodeURIComponent(proposalId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, company_id: companyId }),
  });
  await checkOk(res);
  return res.json();
}

export async function getPlatformStatus(): Promise<PlatformStatus> {
  const res = await apiFetch(`${BASE}/admin/platform`);
  await checkOk(res);
  return res.json();
}

export async function getDeployEvidence(
  founderId: string,
  stackId = "idea_to_revenue",
  baseUrl = "",
  liveConnectors = false,
  strict = true
): Promise<DeployEvidenceReport> {
  const params = new URLSearchParams({
    founder_id: founderId,
    stack_id: stackId,
    live_connectors: String(liveConnectors),
    strict: String(strict),
  });
  if (baseUrl) params.set("base_url", baseUrl);
  const res = await apiFetch(`${BASE}/admin/deploy-evidence?${params}`);
  await checkOk(res);
  return res.json();
}

export async function getProductionRequirements(
  founderId: string,
  stackId = "idea_to_revenue",
  baseUrl = ""
): Promise<ProductionRequirements> {
  const params = new URLSearchParams({ founder_id: founderId, stack_id: stackId });
  if (baseUrl) params.set("base_url", baseUrl);
  const res = await apiFetch(`${BASE}/admin/production-requirements?${params}`);
  await checkOk(res);
  return res.json();
}

export async function getLaunchReadiness(
  founderId: string,
  stackId = "idea_to_revenue",
  baseUrl = "",
  reportId = "latest"
): Promise<LaunchReadiness> {
  const params = new URLSearchParams({ founder_id: founderId, stack_id: stackId, report_id: reportId });
  if (baseUrl) params.set("base_url", baseUrl);
  const res = await apiFetch(`${BASE}/admin/launch-readiness?${params}`);
  await checkOk(res);
  return res.json();
}

export async function runProductionVerification(
  body: { founder_id: string; base_url: string; stack_id?: string; live_connectors?: boolean; save?: boolean }
): Promise<ProductionVerificationReport> {
  const params = new URLSearchParams({
    founder_id: body.founder_id,
    base_url: body.base_url,
    stack_id: body.stack_id ?? "idea_to_revenue",
    live_connectors: String(body.live_connectors ?? true),
    save: String(body.save ?? true),
  });
  const res = await apiFetch(`${BASE}/admin/production-verification?${params}`, { method: "POST" });
  await checkOk(res);
  return res.json();
}

export async function runProductionLaunch(
  body: { founder_id: string; base_url: string; stack_id?: string; live_connectors?: boolean }
): Promise<ProductionLaunchResult> {
  const params = new URLSearchParams({
    founder_id: body.founder_id,
    base_url: body.base_url,
    stack_id: body.stack_id ?? "idea_to_revenue",
    live_connectors: String(body.live_connectors ?? true),
  });
  const res = await apiFetch(`${BASE}/admin/production-launch?${params}`, { method: "POST" });
  await checkOk(res);
  return res.json();
}

export async function getProductionLaunchProof(proofId = "latest"): Promise<ProductionLaunchProofResponse> {
  const res = await apiFetch(`${BASE}/admin/production-launch/reports/${encodeURIComponent(proofId)}`);
  await checkOk(res);
  return res.json();
}

export async function getProductionVerificationReports(limit = 5): Promise<ProductionVerificationReports> {
  const res = await apiFetch(`${BASE}/admin/production-verification/reports?limit=${encodeURIComponent(String(limit))}`);
  await checkOk(res);
  return res.json();
}

export function productionVerificationMarkdownUrl(reportId = "latest"): string {
  return `${BASE}/admin/production-verification/reports/${encodeURIComponent(reportId)}/markdown`;
}

export function productionVerificationBundleUrl(reportId = "latest"): string {
  return `${BASE}/admin/production-verification/reports/${encodeURIComponent(reportId)}/bundle`;
}

export async function verifyProductionVerificationManifest(reportId = "latest"): Promise<ProductionVerificationManifestVerification> {
  const res = await apiFetch(`${BASE}/admin/production-verification/reports/${encodeURIComponent(reportId)}/manifest/verify`);
  await checkOk(res);
  return res.json();
}

export async function getOrganization(orgId: string, founderId = ""): Promise<OrganizationAccount> {
  const params = new URLSearchParams();
  if (founderId) params.set("founder_id", founderId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const res = await apiFetch(`${BASE}/orgs/${encodeURIComponent(orgId)}${suffix}`);
  await checkOk(res);
  return res.json();
}

export interface OrganizationInvite {
  token: string;
  org_id: string;
  org_name?: string;
  kind?: string;
  invited_by: string;
  email: string;
  role?: string;
  status: string;
  created_at?: string;
  expires_at?: string;
}

export async function createOrganizationInvite(
  orgId: string,
  body: { email?: string; role?: string }
): Promise<{ ok: boolean; invite: OrganizationInvite; invite_url: string }> {
  const res = await apiFetch(`${BASE}/orgs/${encodeURIComponent(orgId)}/invites`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await checkOk(res);
  return res.json();
}

export async function getOrganizationInvite(token: string): Promise<OrganizationInvite> {
  const res = await apiFetch(`${BASE}/invites/${encodeURIComponent(token)}`);
  await checkOk(res);
  return res.json();
}

export async function acceptOrganizationInvite(token: string, founderId: string): Promise<{ ok: boolean; org: OrganizationAccount }> {
  const res = await apiFetch(`${BASE}/invites/${encodeURIComponent(token)}/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId }),
  });
  await checkOk(res);
  return res.json();
}

export async function updateOrganizationMember(
  orgId: string,
  body: { actor_id: string; user_id: string; role?: string; status?: string }
): Promise<OrganizationAccount> {
  const res = await apiFetch(`${BASE}/orgs/${encodeURIComponent(orgId)}/members`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await checkOk(res);
  return res.json();
}

export async function updateOrganizationSubscription(
  orgId: string,
  body: { actor_id: string; plan?: string; status?: string; stripe_customer_id?: string; stripe_subscription_id?: string; current_period_end?: string }
): Promise<OrganizationAccount> {
  const res = await apiFetch(`${BASE}/orgs/${encodeURIComponent(orgId)}/subscription`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await checkOk(res);
  return res.json();
}

export async function updateOrganizationControls(
  orgId: string,
  body: { actor_id: string; controls: Partial<OrganizationAccount["admin_controls"]> }
): Promise<OrganizationAccount> {
  const res = await apiFetch(`${BASE}/orgs/${encodeURIComponent(orgId)}/controls`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await checkOk(res);
  return res.json();
}

export async function getOrganizationBilling(
  orgId: string
): Promise<{ org: OrganizationAccount; billing: BillingConfigStatus }> {
  const res = await apiFetch(`${BASE}/orgs/${encodeURIComponent(orgId)}/billing`);
  await checkOk(res);
  return res.json();
}

export async function createOrganizationCheckout(
  orgId: string,
  body: { plan: string; success_url?: string; cancel_url?: string; customer_email?: string }
): Promise<BillingSessionResult> {
  const res = await apiFetch(`${BASE}/orgs/${encodeURIComponent(orgId)}/billing/checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await checkOk(res);
  return res.json();
}

export async function createOrganizationBillingPortal(
  orgId: string,
  body: { return_url?: string } = {}
): Promise<BillingSessionResult> {
  const res = await apiFetch(`${BASE}/orgs/${encodeURIComponent(orgId)}/billing/portal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await checkOk(res);
  return res.json();
}

export interface ModelSettingsResponse {
  founder_id: string;
  overrides: Record<string, string>;
  available_models: string[];
  agent_keys: string[];
}

export async function getModelSettings(founderId: string): Promise<ModelSettingsResponse> {
  const res = await apiFetch(`${BASE}/model-settings?founder_id=${encodeURIComponent(founderId)}`);
  await checkOk(res);
  return res.json();
}

export async function setModelOverride(
  founderId: string,
  agentKey: string,
  model: string
): Promise<{ ok: boolean; founder_id: string; agent_key: string; model: string }> {
  const res = await apiFetch(`${BASE}/model-settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, agent_key: agentKey, model }),
  });
  await checkOk(res);
  return res.json();
}

export async function clearModelOverride(
  founderId: string,
  agentKey: string
): Promise<{ ok: boolean; founder_id: string; agent_key: string; was_set: boolean }> {
  const res = await apiFetch(
    `${BASE}/model-settings/${encodeURIComponent(agentKey)}?founder_id=${encodeURIComponent(founderId)}`,
    { method: "DELETE" }
  );
  await checkOk(res);
  return res.json();
}

// ── Library ────────────────────────────────────────────────────────────────────

export interface LibraryFile {
  id: string;
  founder_id: string;
  department: string;
  filename: string;
  content?: string;
  is_canonical: boolean;
  created_at: string;
  updated_at: string;
  size_bytes: number;
  source_path?: string;
  source_tag?: string;
}

export async function getLibraryFiles(
  founderId: string,
  department?: string
): Promise<LibraryFile[]> {
  const params = new URLSearchParams({ founder_id: founderId });
  if (department) params.set("department", department);
  const res = await apiFetch(`${BASE}/library?${params}`);
  await checkOk(res);
  const data = await res.json();
  return data.files ?? [];
}

export async function getLibraryFile(
  founderId: string,
  fileId: string
): Promise<LibraryFile> {
  const res = await apiFetch(
    `${BASE}/library/${encodeURIComponent(fileId)}?founder_id=${encodeURIComponent(founderId)}`
  );
  await checkOk(res);
  const data = await res.json();
  return data.file;
}

export async function createLibraryFile(body: {
  founder_id: string;
  department: string;
  filename: string;
  content: string;
  is_canonical?: boolean;
}): Promise<LibraryFile> {
  const res = await apiFetch(`${BASE}/library`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await checkOk(res);
  const data = await res.json();
  return data.file;
}

export async function updateLibraryFile(
  fileId: string,
  body: {
    founder_id: string;
    content?: string;
    filename?: string;
    department?: string;
    is_canonical?: boolean;
  }
): Promise<LibraryFile> {
  const res = await apiFetch(`${BASE}/library/${encodeURIComponent(fileId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await checkOk(res);
  const data = await res.json();
  return data.file;
}

export async function deleteLibraryFile(
  founderId: string,
  fileId: string
): Promise<void> {
  const res = await apiFetch(
    `${BASE}/library/${encodeURIComponent(fileId)}?founder_id=${encodeURIComponent(founderId)}`,
    { method: "DELETE" }
  );
  await checkOk(res);
}

export interface ExampleFile {
  path: string;
  category: string;
  title: string;
  tags: string[];
  content: string;
}

export async function getExamplesLibrary(): Promise<ExampleFile[]> {
  const res = await apiFetch(`${BASE}/library/examples`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.examples ?? [];
}

// ── Staged deployments ─────────────────────────────────────────────────────────

export interface DeploymentRecord {
  session_id: string;
  founder_id: string;
  staging_url: string;
  prod_url: string | null;
  staged_at: string;
  published_at: string | null;
  status: "staged" | "published" | "none";
}

export async function getDeployment(sessionId: string): Promise<DeploymentRecord | null> {
  const res = await apiFetch(`${BASE}/deployments/${encodeURIComponent(sessionId)}`);
  if (res.status === 404) return null;
  await checkOk(res);
  return res.json();
}

export async function listDeployments(founderId: string): Promise<DeploymentRecord[]> {
  const res = await apiFetch(`${BASE}/deployments?founder_id=${encodeURIComponent(founderId)}`);
  await checkOk(res);
  const data = await res.json();
  return data.deployments ?? [];
}

export async function publishDeployment(
  sessionId: string,
  vercelToken: string,
  domain?: string
): Promise<{ ok: boolean; prod_url: string | null; error?: string }> {
  const res = await apiFetch(`${BASE}/deployments/${encodeURIComponent(sessionId)}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vercel_token: vercelToken, domain: domain ?? null }),
  });
  if (!res.ok) {
    const text = await res.text();
    return { ok: false, prod_url: null, error: text };
  }
  return res.json();
}

export const AGENT_LABELS: Record<string, string> = {
  planner: "Planner",
  strategy: "Strategy",
  research: "Market Research",
  research_competitors: "Competitor Intel",
  research_execution: "Execution Strategy",
  research_market: "Market Analysis",
  research_financial: "Financial Research",
  research_regulatory: "Regulatory Research",
  web: "Web & Landing Page",
  web_navigator: "Web Navigator",
  marketing: "Marketing & Social",
  marketing_content: "Content Creation",
  marketing_outreach: "Outreach Campaigns",
  marketing_seo: "SEO Strategy",
  marketing_paid: "Paid Advertising",
  technical: "Technical Architecture",
  technical_scaffold: "Code Scaffold",
  technical_infra: "Infrastructure",
  technical_data: "Data Architecture",
  legal: "Legal & Compliance",
  legal_docs: "Legal Documents",
  legal_entity: "Entity Formation",
  legal_ip: "IP & Patents",
  ops: "Ops & Fundraising",
  operations: "Operations",
  sales: "Sales & Outreach",
  sales_pipeline: "Sales Pipeline",
  sales_enablement: "Sales Enablement",
  design: "Design & Brand",
  finance: "Finance",
  finance_model: "Financial Model",
  finance_fundraise: "Fundraising",
};

export const AGENT_ORDER = [
  "planner", "strategy",
  "research", "research_competitors", "research_execution", "research_market", "research_financial", "research_regulatory",
  "design",
  "technical", "technical_scaffold", "technical_infra", "technical_data",
  "web", "web_navigator",
  "marketing", "marketing_content", "marketing_outreach", "marketing_seo", "marketing_paid",
  "legal", "legal_docs", "legal_entity", "legal_ip",
  "sales", "sales_pipeline", "sales_enablement",
  "finance", "finance_model", "finance_fundraise",
  "operations", "ops",
];

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

// ── Missions ───────────────────────────────────────────────────────────────────

export interface MissionTask {
  id: string;
  title: string;
  status: "pending" | "in_progress" | "awaiting_approval" | "done" | "blocked";
  parent_id: string | null;
  notes: string;
  owner_agent: string;
  created_at: string;
  updated_at: string;
  last_run_id?: string | null;
  notion_page_id?: string | null;
  notion_page_url?: string | null;
}

export interface CompanyTask {
  id: string;
  title: string;
  status: "pending" | "in_progress" | "awaiting_approval" | "done" | "blocked";
  owner_agents?: string[];
  done_agents?: string[];
  postponed?: boolean;
  notes: string;
  created_at: string;
  updated_at: string;
  last_run_id?: string | null;
}

export interface CompanyGoalEntry {
  id: string;
  title: string;
  status: "active" | "done" | "proposed";
  kind: "launch" | "planner";
  tasks: CompanyTask[];
  created_at: string;
  completed_at?: string | null;
  credits_used?: number;
}

export interface OperatingRun {
  session_id: string;
  started_at: string;
  status: string;
  summary?: string;
  goal_id?: string;
  credits_used?: number;
}

export interface CompanyGoal {
  founder_id: string;
  company_id?: string;
  north_star: string;
  company_goal: string;
  source_session_id: string;
  root_session_id?: string;
  status: "operating" | "blocked" | "paused" | "completed";
  kpis: Array<{ key?: string; label?: string; target?: string }>;
  goals?: CompanyGoalEntry[];
  current_goal_id?: string;
  operating_sessions?: OperatingRun[];
  updated_at: string;
  notion_database_id?: string | null;
  notion_url?: string | null;
  credits_used_total?: number;
}

export async function postponeCompanyTask(
  founderId: string, taskId: string, postponed = true, companyId = ""
): Promise<{ ok: boolean; task: CompanyTask }> {
  const res = await apiFetch(`${BASE}/missions/company-goal/tasks/${encodeURIComponent(taskId)}/postpone`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, company_id: companyId, postponed }),
  });
  await checkOk(res);
  return res.json();
}

export async function markCompanyTaskDone(founderId: string, taskId: string, companyId = ""): Promise<CompanyTask> {
  const res = await apiFetch(`${BASE}/missions/company-goal/tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, company_id: companyId, status: "done" }),
  });
  await checkOk(res);
  return (await res.json()).task;
}

export async function runCompanyCycle(founderId: string, companyId = ""): Promise<{ ok: boolean; session_id?: string; parent_session_id: string }> {
  const params = new URLSearchParams({ founder_id: founderId });
  if (companyId) params.set("company_id", companyId);
  const res = await apiFetch(`${BASE}/missions/company-goal/run?${params}`, { method: "POST" });
  await checkOk(res);
  return res.json();
}

export async function approveNextGoal(
  founderId: string, approved = true, companyId = ""
): Promise<{ ok: boolean; goal?: CompanyGoalEntry; rejected?: boolean; session_id?: string }> {
  const res = await apiFetch(`${BASE}/missions/company-goal/approve-next`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, company_id: companyId, approved }),
  });
  await checkOk(res);
  return res.json();
}

export async function setCompanyGoalStatus(founderId: string, status: "operating" | "paused" | "completed", companyId = ""): Promise<{ ok: boolean; status: string }> {
  const params = new URLSearchParams({ founder_id: founderId, status });
  if (companyId) params.set("company_id", companyId);
  const res = await apiFetch(`${BASE}/missions/company-goal/status?${params}`, { method: "PATCH" });
  await checkOk(res);
  return res.json();
}

export interface Mission {
  id: string;
  founder_id: string;
  company_id?: string;
  department: string;
  name: string;
  goal: string;
  primary_metric: string;
  objectives: string[];
  budget: { max_runs_per_day: number; max_cost_usd_per_run: number };
  approval_policy: "auto" | "require_approval";
  status: "active" | "paused" | "completed";
  created_at: string;
  last_run_at: string | null;
  run_count: number;
  total_cost_usd: number;
  progress_notes: Array<{ timestamp: string; note: string; run_id: string }>;
  tasks: MissionTask[];
  company_goal_id?: string | null;
  notion_page_id?: string | null;
  notion_page_url?: string | null;
}

export async function getMissions(founderId: string, companyId = ""): Promise<Mission[]> {
  const params = new URLSearchParams({ founder_id: founderId });
  if (companyId) params.set("company_id", companyId);
  const res = await apiFetch(`${BASE}/missions?${params}`);
  await checkOk(res);
  const data = await res.json();
  return data.missions ?? [];
}

export async function createMission(
  data: Omit<Mission, "id" | "created_at" | "last_run_at" | "run_count" | "total_cost_usd" | "progress_notes" | "tasks" | "company_goal_id" | "notion_page_id" | "notion_page_url">
): Promise<Mission> {
  const res = await apiFetch(`${BASE}/missions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  await checkOk(res);
  const result = await res.json();
  return result.mission ?? result;
}

export async function updateMission(id: string, data: Partial<Mission>): Promise<Mission> {
  const res = await apiFetch(`${BASE}/missions/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  await checkOk(res);
  const result = await res.json();
  return result.mission ?? result;
}

export async function deleteMission(id: string): Promise<void> {
  const res = await apiFetch(`${BASE}/missions/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  await checkOk(res);
}

export async function runMission(id: string): Promise<{ ok: boolean; session_id: string }> {
  const res = await apiFetch(`${BASE}/missions/${encodeURIComponent(id)}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  await checkOk(res);
  return res.json();
}

export async function getCompanyGoal(founderId: string, companyId = ""): Promise<CompanyGoal | null> {
  const params = new URLSearchParams({ founder_id: founderId });
  if (companyId) params.set("company_id", companyId);
  const res = await apiFetch(`${BASE}/missions/company-goal?${params}`);
  await checkOk(res);
  const data = await res.json();
  const goal = data.company_goal ?? null;
  if (!goal || !data.current_goal) return goal;
  // Populate current_goal_id so lookups by id work for backward compat
  if (!goal.current_goal_id && data.current_goal.id) {
    goal.current_goal_id = data.current_goal.id;
  }
  return goal;
}

// Founder decision on a milestone the agent finished (awaiting_approval).
// approved → done (+ planner may assign the next milestones); rejected → reopened.
export async function approveMissionTask(
  missionId: string, taskId: string, founderId: string, approved: boolean, note = "", companyId = ""
): Promise<{ ok: boolean; next_milestones_scheduled: boolean }> {
  const res = await apiFetch(`${BASE}/missions/${encodeURIComponent(missionId)}/tasks/${encodeURIComponent(taskId)}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, company_id: companyId, approved, note }),
  });
  await checkOk(res);
  return res.json();
}

export async function getPendingApprovals(founderId: string, companyId = ""): Promise<{ mission_id: string; mission_name: string; department: string; task: MissionTask }[]> {
  const params = new URLSearchParams({ founder_id: founderId });
  if (companyId) params.set("company_id", companyId);
  const res = await apiFetch(`${BASE}/missions/pending-approvals?${params}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.pending ?? [];
}

export async function updateMissionTask(
  missionId: string,
  taskId: string,
  data: Partial<Pick<MissionTask, "title" | "status" | "notes">>
): Promise<MissionTask> {
  const res = await apiFetch(`${BASE}/missions/${encodeURIComponent(missionId)}/tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  await checkOk(res);
  const result = await res.json();
  return result.task ?? result;
}

export async function syncMissionNotion(founderId: string, companyId = ""): Promise<Record<string, unknown>> {
  const res = await apiFetch(`${BASE}/missions/sync-notion`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, company_id: companyId }),
  });
  await checkOk(res);
  return res.json();
}

// ---------------------------------------------------------------------------
// Skills API
// ---------------------------------------------------------------------------

export interface Skill {
  id: string;
  founder_id: string;
  name: string;
  description: string;
  content: string;
  agent_keys: string[];
  created_at: string;
  is_builtin: boolean;
}

export async function listSkills(founderId: string): Promise<Skill[]> {
  const res = await apiFetch(`${BASE}/skills?founder_id=${encodeURIComponent(founderId)}`);
  await checkOk(res);
  const data = await res.json();
  return data.skills ?? [];
}

export async function getSkill(founderId: string, skillId: string): Promise<Skill> {
  const res = await apiFetch(
    `${BASE}/skills/${encodeURIComponent(skillId)}?founder_id=${encodeURIComponent(founderId)}`
  );
  await checkOk(res);
  const data = await res.json();
  return data.skill;
}

export async function createSkill(
  founderId: string,
  body: { name: string; description?: string; content?: string; agent_keys?: string[]; is_builtin?: boolean }
): Promise<Skill> {
  const res = await apiFetch(`${BASE}/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, ...body }),
  });
  await checkOk(res);
  const data = await res.json();
  return data.skill;
}

export async function updateSkill(
  founderId: string,
  skillId: string,
  body: { name?: string; description?: string; content?: string; agent_keys?: string[] }
): Promise<Skill> {
  const res = await apiFetch(`${BASE}/skills/${encodeURIComponent(skillId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, ...body }),
  });
  await checkOk(res);
  const data = await res.json();
  return data.skill;
}

export async function deleteSkill(founderId: string, skillId: string): Promise<void> {
  const res = await apiFetch(
    `${BASE}/skills/${encodeURIComponent(skillId)}?founder_id=${encodeURIComponent(founderId)}`,
    { method: "DELETE" }
  );
  await checkOk(res);
}

export async function attachSkill(
  founderId: string,
  skillId: string,
  agentKey: string
): Promise<Skill> {
  const res = await apiFetch(
    `${BASE}/skills/${encodeURIComponent(skillId)}/attach?founder_id=${encodeURIComponent(founderId)}&agent_key=${encodeURIComponent(agentKey)}`,
    { method: "POST" }
  );
  await checkOk(res);
  const data = await res.json();
  return data.skill;
}

export async function detachSkill(
  founderId: string,
  skillId: string,
  agentKey: string
): Promise<Skill> {
  const res = await apiFetch(
    `${BASE}/skills/${encodeURIComponent(skillId)}/attach?founder_id=${encodeURIComponent(founderId)}&agent_key=${encodeURIComponent(agentKey)}`,
    { method: "DELETE" }
  );
  await checkOk(res);
  const data = await res.json();
  return data.skill;
}

export async function getSkillsForAgent(
  founderId: string,
  agentKey: string
): Promise<Skill[]> {
  const res = await apiFetch(
    `${BASE}/skills/for-agent?founder_id=${encodeURIComponent(founderId)}&agent_key=${encodeURIComponent(agentKey)}`
  );
  await checkOk(res);
  const data = await res.json();
  return data.skills ?? [];
}

// ── Credits ───────────────────────────────────────────────────────────────────

export interface CreditBalance {
  balance: number;
  total_granted: number;
  total_purchased: number;
  total_used: number;
  transactions: Array<{
    id: string;
    type: string;
    amount: number;
    description: string;
    ts: string;
  }>;
}

export async function getCredits(founderId: string): Promise<CreditBalance> {
  const res = await apiFetch(
    `${BASE}/credits?founder_id=${encodeURIComponent(founderId)}`
  );
  await checkOk(res);
  return res.json();
}

export async function purchaseCredits(
  founderId: string,
  pack: "starter" | "pro" | "scale"
): Promise<{ checkout_url: string }> {
  const res = await apiFetch(`${BASE}/credits/purchase`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, pack }),
  });
  await checkOk(res);
  return res.json();
}

export async function rerunAgent(
  sessionId: string,
  agentName: string,
  founderId: string,
  instruction?: string,
): Promise<{ ok: boolean; session_id: string; agent: string }> {
  const res = await apiFetch(`${BASE}/sessions/${encodeURIComponent(sessionId)}/rerun/${encodeURIComponent(agentName)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: founderId, instruction: instruction ?? "" }),
  });
  await checkOk(res);
  return res.json();
}

// ---------------------------------------------------------------------------
// Custom agents — founder-defined specialists
// ---------------------------------------------------------------------------

export interface CustomAgentToolSpec {
  key: string;
  label: string;
  description: string;
  category: string;
  connector: string | null;
}

export interface CustomAgentSchedule {
  every_days: number;
  enabled: boolean;
  run_at_hour?: number | null;
  run_at_minute?: number | null;
  last_run_at?: string | null;
  next_run_at?: string | null;
}

export interface ConnectorStatus {
  required: string[];
  missing: string[];
  ready: boolean;
}

export interface CustomAgent {
  id: string;
  founder_id: string;
  company_id?: string;
  name: string;
  slug: string;
  role: string;
  tool_keys: string[];
  model: string;
  use_computer: boolean;
  schedule: CustomAgentSchedule | null;
  created_at: string;
  updated_at: string;
  connector_status?: ConnectorStatus;
}

export interface CustomAgentInput {
  name: string;
  role: string;
  tool_keys: string[];
  model?: string;
  use_computer?: boolean;
  schedule?: { every_days: number; enabled: boolean; run_at_hour?: number | null; run_at_minute?: number | null } | null;
  company_id?: string;
}

export interface CustomAgentConnectorMeta {
  key: string;
  label: string;
  kind: "composio" | "key";
  composio_slug: string;
}

export async function getCustomAgentToolCatalog(): Promise<{
  tools: CustomAgentToolSpec[];
  connectors: CustomAgentConnectorMeta[];
}> {
  const res = await apiFetch(`${BASE}/custom-agents/tool-catalog`);
  await checkOk(res);
  return res.json();
}

export async function startConnectorConnect(
  founderId: string,
  connectorKey: string,
): Promise<{ kind: "composio" | "key"; connector: string; label: string; oauth_url?: string; field?: string }> {
  const res = await apiFetch(
    `${BASE}/custom-agents/${encodeURIComponent(founderId)}/connect/${encodeURIComponent(connectorKey)}`,
  );
  await checkOk(res);
  return res.json();
}

export async function listCustomAgents(founderId: string): Promise<CustomAgent[]> {
  const res = await apiFetch(`${BASE}/custom-agents/${encodeURIComponent(founderId)}`);
  await checkOk(res);
  return (await res.json()).agents;
}

export async function createCustomAgent(founderId: string, input: CustomAgentInput): Promise<CustomAgent> {
  const res = await apiFetch(`${BASE}/custom-agents/${encodeURIComponent(founderId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  await checkOk(res);
  return res.json();
}

export async function updateCustomAgent(
  founderId: string,
  agentId: string,
  input: Partial<CustomAgentInput> & { clear_schedule?: boolean },
): Promise<CustomAgent> {
  const res = await apiFetch(`${BASE}/custom-agents/${encodeURIComponent(founderId)}/${encodeURIComponent(agentId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  await checkOk(res);
  return res.json();
}

export async function deleteCustomAgent(founderId: string, agentId: string): Promise<void> {
  const res = await apiFetch(`${BASE}/custom-agents/${encodeURIComponent(founderId)}/${encodeURIComponent(agentId)}`, {
    method: "DELETE",
  });
  await checkOk(res);
}

export async function runCustomAgent(
  founderId: string,
  agentId: string,
  opts: { goal?: string; companyId?: string } = {},
): Promise<{ session_id: string; status: string; agent_id: string }> {
  const res = await apiFetch(`${BASE}/custom-agents/${encodeURIComponent(founderId)}/${encodeURIComponent(agentId)}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal: opts.goal, company_id: opts.companyId }),
  });
  await checkOk(res);
  return res.json();
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

// ── Funding Kit ──────────────────────────────────────────────────────────────

export interface FundingDocument {
  type: string;
  label: string;
  file_id: string;
  filename: string;
  source_path: string;
}

export interface FundingKitStatus {
  generated_at: string | null;
  genome_hash: string;
  needs_refresh: boolean;
  generating: boolean;
  documents: FundingDocument[];
  error?: string;
}

export async function getFundingStatus(founderId: string, companyId?: string): Promise<FundingKitStatus> {
  const params = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
  const res = await apiFetch(`${BASE}/funding/status/${encodeURIComponent(founderId)}${params}`);
  await checkOk(res);
  return res.json();
}

export async function triggerFundingGenerate(founderId: string, companyId?: string): Promise<{ started: boolean }> {
  const params = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
  const res = await apiFetch(`${BASE}/funding/generate/${encodeURIComponent(founderId)}${params}`, { method: "POST" });
  await checkOk(res);
  return res.json();
}
