import assert from "node:assert/strict";
import test from "node:test";

// Node executes TypeScript directly in this repository; TypeScript's project
// checker does not allow the runtime .ts extension without a separate test config.
// @ts-expect-error Runtime import intentionally includes the TypeScript extension.
import { artifactSources, getApprovalRequestMetadata, parseTeamCollection, shouldRetainOriginalSession, stopStatusAfterKill } from "../lib/api.ts";

test("parseTeamCollection accepts GET /teams/me collection responses", () => {
  const team = { id: "team-1", name: "Astra", founder_id: "founder", members: [] };

  assert.deepEqual(parseTeamCollection({ teams: [team] }), team);
  assert.deepEqual(parseTeamCollection({ items: [team] }), team);
  assert.equal(parseTeamCollection({ teams: [] }), null);
});

test("artifactSources never falls back to another agent's result", () => {
  const artifact = { key: "brief", owner_agent: "research" };
  const ownerResult = { report: "Owner output" };
  const sources = artifactSources(artifact, {
    research: { result: ownerResult },
    design: { result: { report: "Unrelated output" } },
  });

  assert.deepEqual(sources, [artifact, ownerResult]);
  assert.deepEqual(artifactSources({ key: "unowned" }, { design: { result: "Unrelated output" } }), [{ key: "unowned" }]);
});

test("stop status rolls back when the kill request fails", () => {
  assert.equal(stopStatusAfterKill("running", false), "running");
  assert.equal(stopStatusAfterKill("running", true), "killed");
});

test("restart retains the original session until replacement confirmation", () => {
  assert.equal(shouldRetainOriginalSession(false, "replacement"), true);
  assert.equal(shouldRetainOriginalSession(true, ""), true);
  assert.equal(shouldRetainOriginalSession(true, "replacement"), false);
});

test("approval request metadata normalizes queue and decision payload fields", () => {
  assert.deepEqual(
    getApprovalRequestMetadata({ approval_id: "approval-1", action_digest: "digest-a" }),
    { requestId: "approval-1", expectedActionDigest: "digest-a" },
  );
  assert.deepEqual(
    getApprovalRequestMetadata({ request_id: "request-2", expected_action_digest: "digest-b" }),
    { requestId: "request-2", expectedActionDigest: "digest-b" },
  );
});
