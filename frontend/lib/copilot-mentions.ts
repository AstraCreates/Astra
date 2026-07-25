export type CopilotMentionKind = "squad" | "member" | "library_file";

export type CopilotMentionOption = {
  kind: CopilotMentionKind;
  id: string;
  token: string;
  label: string;
  group: string;
  subtitle?: string;
  squadId?: string;
  role?: string;
};

export type CopilotMention = {
  kind: CopilotMentionKind;
  id: string;
  label: string;
  squadId?: string;
  role?: string;
};

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "item";
}

export function mentionToken(kind: CopilotMentionKind, label: string): string {
  const prefix = kind === "library_file" ? "file" : kind;
  // Keep the visible token human-readable. The structured id is carried in
  // the request, and the caller can disambiguate duplicate labels locally.
  return `${prefix}_${slug(label)}`;
}

export function extractMentionTokens(value: string): string[] {
  return Array.from(value.matchAll(/(?:^|\s)@([a-z0-9_]+)/gi), (match) => match[1].toLowerCase());
}

export function extractCopilotMentions(value: string, options: CopilotMentionOption[]): CopilotMention[] {
  const optionsByToken = new Map(options.map((option) => [option.token.toLowerCase(), option]));
  const seen = new Set<string>();
  const mentions: CopilotMention[] = [];
  for (const token of extractMentionTokens(value)) {
    const option = optionsByToken.get(token);
    if (!option) continue;
    const key = `${option.kind}:${option.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    mentions.push({ kind: option.kind, id: option.id, label: option.label, ...(option.squadId ? { squadId: option.squadId } : {}), ...(option.role ? { role: option.role } : {}) });
  }
  return mentions;
}
