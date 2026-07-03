// Client-side fallback for "Build with AI" when the backend draft route
// (POST /automations/flows/draft, backend/tools/automation_drafts.py) is
// unavailable. Mirrors that file's heuristics and node schema exactly —
// service-specific actions go through the "integration" node type +
// registry, same as flows built by hand on the canvas.
type DraftNodeType = "trigger" | "prompt" | "integration";

type DraftNode = {
  id: string;
  type: DraftNodeType;
  position: { x: number; y: number };
  config: Record<string, unknown>;
};

type DraftEdge = { source: string; target: string };

export type AutomationDraft = {
  name: string;
  nodes: DraftNode[];
  edges: DraftEdge[];
  explanation: string;
};

function slug(text: string): string {
  return (text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48) || "automation");
}

function makeNode(id: string, type: DraftNodeType, config: Record<string, unknown>, x: number, y: number): DraftNode {
  return { id, type, position: { x, y }, config };
}

export function draftAutomationLocally(prompt: string): AutomationDraft {
  const text = prompt.trim();
  const lowered = text.toLowerCase();
  const title = text.slice(0, 80).trim() || "Untitled automation";
  const nodes: DraftNode[] = [];
  const edges: DraftEdge[] = [];

  nodes.push(makeNode("trigger_1", "trigger", {}, 80, 140));
  let previous = "trigger_1";
  let x = 320;

  const add = (type: DraftNodeType, config: Record<string, unknown>) => {
    const id = `${type}_${nodes.length + 1}`;
    nodes.push(makeNode(id, type, config, x, 140));
    edges.push({ source: previous, target: id });
    previous = id;
    x += 260;
    return id;
  };

  const addIntegration = (blockKey: string, params: Record<string, unknown>) =>
    add("integration", { block_key: blockKey, params });

  if (/(summarize|triage|review|classify|analyze|digest|route)/i.test(text)) {
    add("prompt", { instruction: `${text}\n\nUse any upstream context to produce the next best action.` });
  }

  const hasPrompt = nodes.some((node) => node.type === "prompt");
  const upstreamRef = hasPrompt ? "{{prompt_2.output}}" : text;
  const emailMatch = text.match(/\bemail\s+([^\s,;]+@[^\s,;]+)/i);
  const repoMatch = text.match(/\bgithub\b.*?\b(?:repo|repository)\s+([A-Za-z0-9_.-]+)/i);

  if (lowered.includes("gmail")) {
    addIntegration("gmail_send", { to: emailMatch?.[1] || "", subject: "Astra automation update", body: upstreamRef });
  } else if (lowered.includes("email")) {
    addIntegration("sendgrid_send", { to: emailMatch?.[1] || "", subject: "Astra automation update", body: upstreamRef });
  }

  if (lowered.includes("slack")) {
    addIntegration("slack_webhook_post", { webhook_url: "", message: upstreamRef });
  }

  if (lowered.includes("linear")) {
    addIntegration("linear_create_issue", { title: "Astra follow-up", description: upstreamRef });
  }

  if (lowered.includes("notion")) {
    addIntegration("notion_create_page", { title: "Astra automation note", body: upstreamRef, parent_id: "" });
  }

  if (lowered.includes("github")) {
    addIntegration("github_create_issue", { repo: repoMatch?.[1] || "", owner: "", title: "Astra automation follow-up", body: upstreamRef });
  }

  if (lowered.includes("stripe") || lowered.includes("payment link") || lowered.includes("checkout")) {
    addIntegration("stripe_payment_link", { title: "Astra offer", description: upstreamRef, amount: "99", currency: "usd", interval: "one_time" });
  }

  if (nodes.length === 1) {
    add("prompt", { instruction: text });
  }

  return {
    name: slug(title).replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase()),
    nodes,
    edges,
    explanation: "Drafted locally from natural language using Astra-native block heuristics.",
  };
}
