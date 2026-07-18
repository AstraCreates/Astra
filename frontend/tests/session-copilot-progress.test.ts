import test from "node:test";
import assert from "node:assert/strict";

// @ts-expect-error Runtime import intentionally includes the TypeScript extension.
import { isCurrentCopilotTurn } from "../lib/copilot-turn.ts";

test("Copilot progress only accepts events for the active turn", () => {
  assert.equal(isCurrentCopilotTurn("turn-current", "turn-current"), true);
  assert.equal(isCurrentCopilotTurn("turn-current", "turn-previous"), false);
  assert.equal(isCurrentCopilotTurn("", "turn-current"), false);
});
