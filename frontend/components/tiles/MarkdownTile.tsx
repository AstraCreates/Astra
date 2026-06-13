"use client";

interface Config {
  content?: string;
}

function renderMarkdown(raw: string): React.ReactNode[] {
  const lines = raw.split("\n");
  return lines.map((line, i) => {
    // Heading
    const h3 = line.match(/^###\s+(.+)/);
    const h2 = line.match(/^##\s+(.+)/);
    const h1 = line.match(/^#\s+(.+)/);
    if (h1 || h2 || h3) {
      const text = (h1 || h2 || h3)![1];
      const size = h1 ? 15 : h2 ? 13 : 12;
      return <div key={i} style={{ fontSize: size, fontWeight: 700, color: "var(--fg)", marginBottom: 4, marginTop: i === 0 ? 0 : 8 }}>{text}</div>;
    }
    // Empty line → spacer
    if (!line.trim()) return <div key={i} style={{ height: 6 }} />;
    // Inline bold/italic
    const parts = line.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, j) => {
      if (part.startsWith("**") && part.endsWith("**"))
        return <strong key={j}>{part.slice(2, -2)}</strong>;
      if (part.startsWith("*") && part.endsWith("*"))
        return <em key={j}>{part.slice(1, -1)}</em>;
      return part;
    });
    return <div key={i} style={{ fontSize: 12, color: "var(--fd)", lineHeight: 1.6 }}>{parts}</div>;
  });
}

export default function MarkdownTile({ config }: { config: Config }) {
  const { content = "" } = config;
  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      {renderMarkdown(content)}
    </div>
  );
}
