import assert from "node:assert/strict";
import test from "node:test";

// @ts-expect-error Node's TypeScript runner intentionally imports the source extension.
import { companyScopedUrl, normalizeCompanyHomeData, updateInitiative } from "../lib/company-os.ts";

test("companyScopedUrl carries both company scope identifiers", () => {
  const url = new URL(companyScopedUrl("/missions", { founderId: "founder one", companyId: "company/two" }));
  assert.equal(url.searchParams.get("founder_id"), "founder one");
  assert.equal(url.searchParams.get("company_id"), "company/two");
});

test("normalizeCompanyHomeData accepts nested API payloads and normalizes task lifecycle", () => {
  const home = normalizeCompanyHomeData({
    company_name: "Northstar Labs",
    goal: { north_star: "Reach repeatable demand", goals: [{ id: "i1", title: "Launch", status: "active", tasks: [{ status: "done" }, { status: "in_progress" }] }] },
    missions: [{ id: "m1", name: "Growth", status: "active", tasks: [{ id: "t1", title: "Interview customers", status: "awaiting_approval", owner_agent: "research" }] }],
    approvals: [{ department: "research", task: { id: "t1", title: "Interview customers", notes: "Review the script" } }],
    brain: { summary: "Customer evidence", sources: [{ key: "notion" }], records: [{ id: "a1", title: "Interview notes", source: "notion", updated_at: "today" }] },
  });
  assert.equal(home.companyName, "Northstar Labs");
  assert.equal(home.initiatives[0].progress, 50);
  assert.equal(home.squads[0].tasks[0].status, "waiting");
  assert.equal(home.approvals[0].squad, "Research");
  assert.deepEqual(home.brain.artifacts[0], { id: "a1", title: "Interview notes", source: "Notion", updatedAt: "today", url: undefined, initiativeId: undefined, archived: false });
});

test("normalizes an initiative workspace with its brief, roster, dependencies, artifacts, and timeline", () => {
  const home = normalizeCompanyHomeData({
    name: "Northstar Labs",
    initiatives: [{ initiative_id: "i1", name: "Launch self-serve", state: "active", objective: "Make signup effortless", success_criteria: ["500 trials", "30% activation"], priority: "high", owner: "Maya", budget: "$12,000", due_date: "2026-09-30", dependencies: [{ initiative_id: "i0", name: "Billing migration", state: "complete" }], timeline: [{ event_id: "e1", title: "Brief approved", created_at: "2026-07-20", state: "complete" }] }],
    squads: [{ squad_id: "s1", initiative_id: "i1", name: "Growth squad", roster: [{ display_name: "Maya" }, { name: "Lee" }] }],
    artifacts: [{ artifact_id: "a1", initiative_id: "i1", name: "Launch brief", source: "notion", created_at: "today" }],
    tasks: [], missions: [], approvals: [], context_records: [], conversation: [],
  });
  assert.deepEqual(home.initiatives[0].brief, { objective: "Make signup effortless", successCriteria: "500 trials\n30% activation", priority: "High", owner: "Maya", budget: "$12,000", dueDate: "2026-09-30" });
  assert.deepEqual(home.initiatives[0].dependencies, [{ id: "i0", name: "Billing migration", status: "Complete" }]);
  assert.equal(home.initiatives[0].timeline[0].title, "Brief approved");
  assert.deepEqual(home.squads[0].members, ["Maya", "Lee"]);
  assert.equal(home.brain.artifacts[0].initiativeId, "i1");
});

test("updateInitiative sends the complete editable brief through the company-scoped endpoint", async () => {
  let request: Request | undefined;
  const fetcher = async (input: RequestInfo | URL, init?: RequestInit) => {
    request = new Request(input, init);
    return new Response(JSON.stringify({ company: { name: "Northstar", initiatives: [], squads: [], tasks: [], missions: [], approvals: [], context_records: [], artifacts: [], conversation: [] } }), { status: 200 });
  };
  await updateInitiative({ founderId: "f1", companyId: "c1" }, "i1", { name: "Launch", objective: "Grow", successCriteria: "100 trials\n30% activation", priority: "High", owner: "Maya", budget: "$1000", dueDate: "2026-09-30", status: "Working" }, fetcher as typeof fetch);
  assert.equal(request?.method, "PATCH");
  assert.equal(request?.url, "http://localhost:8000/companies/c1/os/initiatives/i1?founder_id=f1&company_id=c1");
  assert.deepEqual(await request?.json(), { founder_id: "f1", name: "Launch", objective: "Grow", success_criteria: ["100 trials", "30% activation"], priority: "High", owner: "Maya", budget: { summary: "$1000" }, due_date: "2026-09-30", state: "working" });
});
