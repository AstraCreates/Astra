import assert from "node:assert/strict";
import test from "node:test";

// @ts-expect-error Node's TypeScript runner intentionally imports the source extension.
import { companyScopedUrl, normalizeCompanyHomeData } from "../lib/company-os.ts";

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
  assert.deepEqual(home.brain.artifacts[0], { id: "a1", title: "Interview notes", source: "Notion", updatedAt: "today", url: undefined });
});
