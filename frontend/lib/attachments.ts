// Lightweight client-side file attachments for the goal prompt and chat.
// Text-like files are read inline and embedded into the prompt so every agent
// sees them. Binary files (images, PDFs) aren't text-extractable here and are
// rejected with a clear message rather than silently dropped.

export interface Attachment {
  name: string;
  content: string;
  truncated: boolean;
  error?: string;
}

const MAX_CHARS = 20000; // per-file cap to keep prompts sane
const TEXT_EXT = /\.(txt|md|markdown|csv|tsv|json|ya?ml|xml|html?|css|scss|js|jsx|ts|tsx|py|rb|go|rs|java|c|cpp|h|sh|sql|env|ini|toml|log|text)$/i;

export function isTextFile(file: File): boolean {
  return TEXT_EXT.test(file.name) || file.type.startsWith("text/") || file.type === "application/json";
}

export async function readAttachment(file: File): Promise<Attachment> {
  if (!isTextFile(file)) {
    return { name: file.name, content: "", truncated: false, error: "Unsupported file type — attach a text/CSV/code/markdown file." };
  }
  try {
    let text = await file.text();
    const truncated = text.length > MAX_CHARS;
    if (truncated) text = text.slice(0, MAX_CHARS) + "\n…[truncated]";
    return { name: file.name, content: text, truncated };
  } catch {
    return { name: file.name, content: "", truncated: false, error: "Could not read file." };
  }
}

/** Build a prompt block from valid attachments (skips ones with errors). */
export function buildAttachmentBlock(atts: Attachment[]): string {
  const valid = atts.filter(a => !a.error && a.content);
  if (!valid.length) return "";
  const parts = valid.map(a => `--- Attached file: ${a.name} ---\n${a.content}`);
  return `\n\nAttached files for context:\n${parts.join("\n\n")}`;
}

// deploy-pipeline check: frontend auto-deploy via autopull
