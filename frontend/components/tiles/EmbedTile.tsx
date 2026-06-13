"use client";

interface Config {
  url?: string;
  height?: number;
}

export default function EmbedTile({ config }: { config: Config }) {
  const { url = "", height = 300 } = config;
  const safeUrl = /^https?:\/\//i.test(url) ? url : "";
  if (!safeUrl) {
    return <div style={{ fontSize: 12, color: "var(--fm)", paddingTop: 8 }}>No URL configured.</div>;
  }
  return (
    <iframe
      src={safeUrl}
      sandbox="allow-scripts allow-forms allow-popups"
      style={{
        width: "100%",
        height: height,
        border: "none",
        borderRadius: 6,
        display: "block",
      }}
      loading="lazy"
    />
  );
}
