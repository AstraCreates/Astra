// @ts-expect-error Node's direct TypeScript test runner requires the extension.
import { apiFetch } from "./api.ts";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type CompanyScope = { founderId: string; companyId: string };

export type CompanyHomeTask = {
  id: string;
  title: string;
  status: "planned" | "active" | "waiting" | "complete" | "blocked";
  squad: string;
  note: string;
};

export type CompanyInitiativeDependency = { id: string; name: string; status: string };
export type CompanyInitiativeTimelineItem = { id: string; title: string; detail: string; occurredAt: string; status: string };
export type CompanyInitiativeBrief = { objective: string; successCriteria: string; priority: string; owner: string; budget: string; dueDate: string };
export type CompanyHomeInitiative = { id: string; title: string; status: string; progress: number; taskCount: number; archived: boolean; brief: CompanyInitiativeBrief; dependencies: CompanyInitiativeDependency[]; timeline: CompanyInitiativeTimelineItem[] };
export type CompanyHomeSquad = { id: string; initiativeId: string; name: string; lifecycle: string; activity: string; members: string[]; tasks: CompanyHomeTask[]; archived: boolean };
export type CompanyHomeApproval = { id: string; title: string; squad: string; detail: string };
export type CompanyHomeArtifact = { id: string; title: string; source: string; updatedAt: string; url?: string; initiativeId?: string; archived: boolean };
export type CompanyArtifactDetail = CompanyHomeArtifact & { content: string; sourceReferences: unknown[] };
export type CompanyHomeBrain = { summary: string; sourceCount: number; recordCount: number; artifacts: CompanyHomeArtifact[] };
export type CompanyHomeMessage = { id: string; author: string; message: string; kind: "chat" | "status" | "question"; edited: boolean; question?: string; options?: string[] };

export type CompanyHomeData = {
  companyName: string;
  northStar: string;
  initiatives: CompanyHomeInitiative[];
  squads: CompanyHomeSquad[];
  approvals: CompanyHomeApproval[];
  brain: CompanyHomeBrain;
  conversation: CompanyHomeMessage[];
};

type UnknownRecord = Record<string, unknown>;
export type InitiativeBriefUpdate = CompanyInitiativeBrief & { name: string; status: string };

function record(value: unknown): UnknownRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function taskStatus(value: unknown): CompanyHomeTask["status"] {
  const status = text(value).toLowerCase().replaceAll("_", " ");
  if (["done", "complete", "completed"].includes(status)) return "complete";
  if (["in progress", "active", "working"].includes(status)) return "active";
  if (["awaiting approval", "waiting", "pending approval"].includes(status)) return "waiting";
  if (["blocked", "failed"].includes(status)) return "blocked";
  return "planned";
}

function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function initiativeStatus(value: unknown): string {
  const status = text(value, "planned").toLowerCase();
  if (["active", "working", "in_progress"].includes(status)) return "Working";
  if (["waiting", "review", "awaiting_approval"].includes(status)) return "Review";
  if (["complete", "completed", "done"].includes(status)) return "Done";
  return "Planned";
}

function criteria(value: unknown): string {
  return list(value).map(item => text(item)).filter(Boolean).join("\n") || text(value);
}

function budget(value: unknown): string {
  if (typeof value === "string") return text(value);
  const details = record(value);
  const amount = details.summary ?? details.amount ?? details.amount_usd ?? details.limit_usd ?? details.total;
  return amount === undefined || amount === null ? "" : String(amount);
}

function members(value: unknown): string[] {
  return list(value).map(item => {
    const member = record(item);
    return text(typeof item === "string" ? item : member.name ?? member.display_name ?? member.agent_name ?? member.role);
  }).filter(Boolean);
}

function initiativeDependencies(value: unknown): CompanyInitiativeDependency[] {
  return list(value).map((item, index) => {
    const dependency = record(item);
    return { id: text(dependency.id ?? dependency.initiative_id, `dependency-${index}`), name: text(typeof item === "string" ? item : dependency.name ?? dependency.title, "Untitled dependency"), status: titleCase(text(dependency.status ?? dependency.state, "planned")) };
  });
}

function timeline(value: unknown): CompanyInitiativeTimelineItem[] {
  return list(value).map((item, index) => {
    const event = record(item);
    return { id: text(event.id ?? event.event_id, `timeline-${index}`), title: text(event.title ?? event.name ?? event.message, "Activity recorded"), detail: text(event.detail ?? event.description ?? event.note), occurredAt: text(event.occurred_at ?? event.created_at ?? event.updated_at ?? event.date, "Recently"), status: titleCase(text(event.status ?? event.state, "updated")) };
  });
}

function brief(initiative: UnknownRecord): CompanyInitiativeBrief {
  return {
    objective: text(initiative.objective ?? initiative.description ?? initiative.goal),
    successCriteria: criteria(initiative.success_criteria ?? initiative.successCriteria),
    priority: titleCase(text(initiative.priority, "Medium")),
    owner: text(initiative.owner ?? initiative.owner_name ?? initiative.owner_agent),
    budget: budget(initiative.budget ?? initiative.budget_amount ?? initiative.budgetAmount),
    dueDate: text(initiative.due_date ?? initiative.dueDate ?? initiative.target_date),
  };
}

export function companyScopedUrl(path: string, scope: CompanyScope): string {
  if (BASE.startsWith("/")) {
    const params = new URLSearchParams({ founder_id: scope.founderId, company_id: scope.companyId });
    return `${BASE.replace(/\/$/, "")}${path}?${params.toString()}`;
  }
  const url = new URL(`${BASE}${path}`);
  url.searchParams.set("founder_id", scope.founderId);
  url.searchParams.set("company_id", scope.companyId);
  return url.toString();
}

export function normalizeCompanyHomeData(payload: unknown, companyName = "Your company"): CompanyHomeData {
  const root = record(payload);
  const goal = record(root.goal ?? root.company_goal);
  const missionPayload = record(root.missions);
  const missions = list(root.missions ?? missionPayload.missions);
  const squadPayload = missions.length ? missions : list(root.squads);
  const pending = list(root.approvals ?? root.pending);
  const brain = record(root.brain);
  const records = list(brain.records ?? root.records);
  const sources = list(brain.sources ?? root.sources);
  const initiatives = list(goal.goals ?? root.initiatives).map((item, index) => {
    const initiative = record(item);
    const tasks = list(initiative.tasks);
    const completed = tasks.filter((task) => taskStatus(record(task).status) === "complete").length;
    return {
      id: text(initiative.id, `initiative-${index}`),
      title: text(initiative.title ?? initiative.name, "Untitled initiative"),
      status: initiativeStatus(initiative.status),
      progress: tasks.length ? Math.round((completed / tasks.length) * 100) : 0,
      taskCount: tasks.length,
      archived: text(initiative.status).toLowerCase() === "archived",
      brief: brief(initiative), dependencies: initiativeDependencies(initiative.dependencies), timeline: timeline(initiative.timeline ?? initiative.activity ?? initiative.roadmap),
    };
  }).filter((initiative) => !initiative.archived);
  const squads = squadPayload.map((item, index) => {
    const mission = record(item);
    const missionTasks = list(mission.tasks).map((task, taskIndex): CompanyHomeTask => {
      const value = record(task);
      return {
        id: text(value.id, `task-${index}-${taskIndex}`),
        title: text(value.title ?? value.name, "Untitled task"),
        status: taskStatus(value.status),
        squad: titleCase(text(value.owner_agent ?? mission.department, "Operations")),
        note: text(value.notes ?? value.detail),
      };
    });
    const lifecycle = titleCase(text(mission.status, "active"));
    const active = missionTasks.find((task) => task.status === "active") ?? missionTasks[0];
    return {
      id: text(mission.id, `squad-${index}`), initiativeId: text(mission.initiative_id),
      name: text(mission.name ?? mission.department, "Operations squad"),
      lifecycle,
      activity: active ? active.title : text(mission.goal, "Setting direction"),
      members: members(mission.members ?? mission.roster ?? mission.agents),
      tasks: missionTasks,
      archived: false,
    };
  });
  const approvals = pending.map((item, index): CompanyHomeApproval => {
    const approval = record(item);
    const task = record(approval.task);
    return {
      id: text(task.task_id ?? task.id ?? approval.approval_id ?? approval.id, `approval-${index}`),
      title: text(task.title ?? approval.title, "Decision requested"),
      squad: titleCase(text(approval.department ?? task.owner_agent, "Operations")),
      detail: text(task.notes ?? approval.detail, "A teammate needs your direction before continuing."),
    };
  });
  const artifactPayload = records.length ? records : list(root.artifacts);
  const artifacts = artifactPayload.slice(0, 8).map((item, index): CompanyHomeArtifact => {
    const artifact = record(item);
    return {
      id: text(artifact.id, `artifact-${index}`),
      title: text(artifact.title ?? artifact.name, "Untitled artifact"),
      source: titleCase(text(artifact.source ?? artifact.kind, "Company Brain")),
      updatedAt: text(artifact.updated_at ?? artifact.created_at, "Recently"),
      url: text(artifact.url) || undefined,
      initiativeId: text(artifact.initiative_id) || undefined,
      archived: false,
    };
  });
  return {
    companyName: text(root.company_name ?? root.companyName, companyName),
    northStar: text(goal.north_star ?? goal.company_goal, "Set a clear company direction to focus the work."),
    initiatives,
    squads,
    approvals,
    brain: {
      summary: text(brain.summary ?? brain.context, "Company knowledge is ready to ground each decision."),
      sourceCount: sources.length,
      recordCount: records.length,
      artifacts,
    },
    conversation: [],
  };
}

export async function getCompanyHomeData(scope: CompanyScope, fetcher: typeof apiFetch = apiFetch): Promise<CompanyHomeData> {
  const response = await fetcher(companyScopedUrl(`/companies/${encodeURIComponent(scope.companyId)}/os`, scope));
  if (!response.ok) throw new Error(await response.text());
  return normalizeCompanyOS(await response.json());
}

export async function sendCopilotMessage(scope: CompanyScope, message: string, fetcher: typeof apiFetch = apiFetch): Promise<{ message: string; data: CompanyHomeData }> {
  const response = await fetcher(`${BASE}/companies/${encodeURIComponent(scope.companyId)}/os/copilot`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: scope.founderId, message }),
  });
  if (!response.ok) throw new Error(await response.text());
  const payload = record(await response.json());
  return { message: text(payload.message), data: normalizeCompanyOS(payload.company) };
}

export async function deleteInitiative(scope: CompanyScope, initiativeId: string, fetcher: typeof apiFetch = apiFetch): Promise<CompanyHomeData> {
  const response = await fetcher(companyScopedUrl(`/companies/${encodeURIComponent(scope.companyId)}/os/initiatives/${encodeURIComponent(initiativeId)}`, scope), { method: "DELETE" });
  if (!response.ok) throw new Error(await response.text());
  const payload = record(await response.json());
  return normalizeCompanyOS(payload.company);
}

export async function updateInitiative(scope: CompanyScope, initiativeId: string, update: InitiativeBriefUpdate, fetcher: typeof apiFetch = apiFetch): Promise<CompanyHomeData> {
  const response = await fetcher(companyScopedUrl(`/companies/${encodeURIComponent(scope.companyId)}/os/initiatives/${encodeURIComponent(initiativeId)}`, scope), {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: scope.founderId, name: update.name, objective: update.objective, success_criteria: update.successCriteria.split("\n").map(item => item.trim()).filter(Boolean), priority: update.priority, owner: update.owner, budget: update.budget ? { summary: update.budget } : {}, due_date: update.dueDate, state: ({ Planned: "planned", Working: "working", Review: "review", Done: "done" } as Record<string, string>)[update.status] ?? "planned" }),
  });
  if (!response.ok) throw new Error(await response.text());
  const payload = record(await response.json());
  return normalizeCompanyOS(payload.company ?? payload);
}

export async function deleteSquad(scope: CompanyScope, squadId: string, fetcher: typeof apiFetch = apiFetch): Promise<CompanyHomeData> {
  const response = await fetcher(companyScopedUrl(`/companies/${encodeURIComponent(scope.companyId)}/os/squads/${encodeURIComponent(squadId)}`, scope), { method: "DELETE" });
  if (!response.ok) throw new Error(await response.text());
  const payload = record(await response.json());
  return normalizeCompanyOS(payload.company);
}

export async function deleteArtifact(scope: CompanyScope, artifactId: string, fetcher: typeof apiFetch = apiFetch): Promise<CompanyHomeData> {
  const response = await fetcher(companyScopedUrl(`/companies/${encodeURIComponent(scope.companyId)}/os/artifacts/${encodeURIComponent(artifactId)}`, scope), { method: "DELETE" });
  if (!response.ok) throw new Error(await response.text());
  const payload = record(await response.json());
  return normalizeCompanyOS(payload.company);
}

export async function editMessage(scope: CompanyScope, messageId: string, message: string, fetcher: typeof apiFetch = apiFetch): Promise<CompanyHomeData> {
  const response = await fetcher(companyScopedUrl(`/companies/${encodeURIComponent(scope.companyId)}/os/messages/${encodeURIComponent(messageId)}`, scope), {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ founder_id: scope.founderId, message }),
  });
  if (!response.ok) throw new Error(await response.text());
  const payload = record(await response.json());
  return normalizeCompanyOS(payload.company);
}

export async function deleteMessage(scope: CompanyScope, messageId: string, fetcher: typeof apiFetch = apiFetch): Promise<CompanyHomeData> {
  const response = await fetcher(companyScopedUrl(`/companies/${encodeURIComponent(scope.companyId)}/os/messages/${encodeURIComponent(messageId)}`, scope), { method: "DELETE" });
  if (!response.ok) throw new Error(await response.text());
  const payload = record(await response.json());
  return normalizeCompanyOS(payload.company);
}

export async function clearMessages(scope: CompanyScope, fetcher: typeof apiFetch = apiFetch): Promise<CompanyHomeData> {
  const response = await fetcher(companyScopedUrl(`/companies/${encodeURIComponent(scope.companyId)}/os/messages/clear`, scope), { method: "POST" });
  if (!response.ok) throw new Error(await response.text());
  const payload = record(await response.json());
  return normalizeCompanyOS(payload.company);
}

export async function decideCompanyApproval(scope: CompanyScope, approvalId: string, approved: boolean, fetcher: typeof apiFetch = apiFetch): Promise<CompanyHomeData> {
  const response = await fetcher(companyScopedUrl(`/companies/${encodeURIComponent(scope.companyId)}/os/approvals/${encodeURIComponent(approvalId)}`, scope), { method: "POST", body: JSON.stringify({ founder_id: scope.founderId, approved }) });
  if (!response.ok) throw new Error(await response.text());
  const payload = record(await response.json());
  return normalizeCompanyOS(payload.company);
}

export async function getCompanyArtifact(scope: CompanyScope, artifactId: string, fetcher: typeof apiFetch = apiFetch): Promise<CompanyArtifactDetail> {
  const response = await fetcher(companyScopedUrl(`/companies/${encodeURIComponent(scope.companyId)}/os/artifacts/${encodeURIComponent(artifactId)}`, scope));
  if (!response.ok) throw new Error(await response.text());
  const artifact = record(await response.json());
  return { id: text(artifact.artifact_id, artifactId), title: text(artifact.name, "Untitled artifact"), source: titleCase(text(artifact.source, "Company Brain")), updatedAt: text(artifact.created_at, "Recently"), url: text(artifact.url) || undefined, initiativeId: text(artifact.initiative_id) || undefined, content: text(artifact.content), sourceReferences: list(artifact.source_references), archived: text(artifact.state).toLowerCase() === "archived" };
}

function normalizeCompanyOS(payload: unknown): CompanyHomeData {
  const root = record(payload);
  const tasks = list(root.tasks).map(record);
  const missions = list(root.missions).map(record);
  const squads = list(root.squads).map(record);
  const initiatives = list(root.initiatives).map(record);
  const approvals = list(root.approvals).map(record);
  const brainRecords = list(root.context_records).map(record);
  return {
    companyName: text(root.name, "Your company"),
    northStar: text(brainRecords.find(item => item.key === "north_star")?.value, "Ask Copilot to form your first initiative."),
    initiatives: initiatives
      .map((initiative, index) => {
        const matching = tasks.filter(task => task.initiative_id === initiative.initiative_id);
        const complete = matching.filter(task => taskStatus(task.state) === "complete").length;
        const initiativeTimeline = timeline(initiative.timeline ?? initiative.activity ?? initiative.roadmap);
        const conversationTimeline = list(root.conversation).map(record).filter(message => message.scope_id === initiative.initiative_id).map((message, messageIndex) => ({ id: text(message.message_id, `message-${messageIndex}`), title: text(message.message, "Activity recorded"), detail: titleCase(text(message.author, "Copilot")), occurredAt: text(message.created_at ?? message.updated_at, "Recently"), status: titleCase(text(message.kind, "updated")) }));
        return { id: text(initiative.initiative_id, `initiative-${index}`), title: text(initiative.name, "Untitled initiative"), status: initiativeStatus(initiative.state), progress: matching.length ? Math.round(complete / matching.length * 100) : 0, taskCount: matching.length, archived: text(initiative.state).toLowerCase() === "archived", brief: brief(initiative), dependencies: initiativeDependencies(initiative.dependencies ?? initiative.depends_on), timeline: initiativeTimeline.length ? initiativeTimeline : conversationTimeline };
      })
      .filter(initiative => !initiative.archived),
    squads: squads.map((squad, index) => {
      const matching = tasks.filter(task => task.squad_id === squad.squad_id).map((task, taskIndex) => ({ id: text(task.task_id, `task-${index}-${taskIndex}`), title: text(task.name, "Untitled task"), status: taskStatus(task.state), squad: titleCase(text(squad.department, "Operations")), note: text(task.description) }));
      const mission = missions.find(item => item.squad_id === squad.squad_id);
      const active = matching.find(task => task.status === "active") ?? matching[0];
      return { id: text(squad.squad_id, `squad-${index}`), initiativeId: text(squad.initiative_id), name: text(squad.name, "Squad"), lifecycle: titleCase(text(mission?.state ?? squad.lifecycle, "formed")), activity: active?.title ?? "Setting direction", members: members(squad.members ?? squad.roster ?? squad.agents), tasks: matching, archived: text(squad.state).toLowerCase() === "archived" };
    }).filter(squad => !squad.archived),
    approvals: approvals.filter(item => text(item.state, "pending") === "pending").map((item, index) => ({ id: text(item.approval_id, `approval-${index}`), title: text(item.title, "Decision requested"), squad: titleCase(text(item.department, "Operations")), detail: text(item.detail, "A teammate needs your approval before continuing.") })),
    brain: { summary: brainRecords.length ? "Scoped Company Brain records ground every initiative and squad." : "Company knowledge is ready to ground each decision.", sourceCount: brainRecords.reduce((count, item) => count + list(item.source_references).length, 0), recordCount: brainRecords.length, artifacts: list(root.artifacts).map((item, index) => { const artifact = record(item); return { id: text(artifact.artifact_id, `artifact-${index}`), title: text(artifact.name, "Untitled artifact"), source: titleCase(text(artifact.source, "Company Brain")), updatedAt: text(artifact.created_at, "Recently"), url: text(artifact.url) || undefined, initiativeId: text(artifact.initiative_id) || undefined, archived: text(artifact.state).toLowerCase() === "archived" }; }).filter(artifact => !artifact.archived) },
    conversation: list(root.conversation).filter(item => !record(item).archived).map((item, index) => {
      const message = record(item);
      const kindRaw = text(message.kind, "chat");
      const kind = kindRaw === "status" ? "status" : kindRaw === "question" ? "question" : "chat";
      const options = list(message.options).map(option => text(option)).filter(Boolean);
      return {
        id: text(message.message_id, `message-${index}`), author: text(message.author, "copilot"), message: text(message.message),
        kind, edited: Boolean(message.edited),
        ...(kind === "question" ? { question: text(message.question) || undefined, options: options.length ? options : undefined } : {}),
      };
    }),
  };
}
