import assert from "node:assert/strict";
import test from "node:test";

// @ts-expect-error Runtime import intentionally includes the TypeScript extension.
import { extractCopilotMentions, mentionToken, type CopilotMentionOption } from "../lib/copilot-mentions.ts";

test("extractCopilotMentions resolves squads, members, and Library files into structured references", () => {
  const options: CopilotMentionOption[] = [
    { kind: "squad", id: "squad-1", token: "squad_insights", label: "Insights", group: "Squads" },
    { kind: "member", id: "squad-1:Market Analyst:Maya", token: "member_maya", label: "Maya", group: "Squad members", squadId: "squad-1", role: "Market Analyst" },
    { kind: "library_file", id: "file-1", token: "file_launch_brief", label: "Launch brief.md", group: "Library", subtitle: "Research" },
  ];

  assert.deepEqual(extractCopilotMentions("Ask @squad_insights and @member_maya using @file_launch_brief", options), [
    { kind: "squad", id: "squad-1", label: "Insights" },
    { kind: "member", id: "squad-1:Market Analyst:Maya", label: "Maya", squadId: "squad-1", role: "Market Analyst" },
    { kind: "library_file", id: "file-1", label: "Launch brief.md" },
  ]);
});

test("mention extraction deduplicates repeated tokens and ignores unknown handles", () => {
  const option: CopilotMentionOption = { kind: "squad", id: "s1", token: "squad_insights", label: "Insights", group: "Squads" };
  assert.deepEqual(extractCopilotMentions("@squad_insights @squad_insights @missing", [option]), [
    { kind: "squad", id: "s1", label: "Insights" },
  ]);
});

test("visible mention tokens stay readable and do not expose internal ids", () => {
  assert.equal(mentionToken("library_file", "Research evidence.md"), "file_research_evidence_md");
});
