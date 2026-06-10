"use client";

import { useState } from "react";

const SI = "https://cdn.simpleicons.org";

export const SERVICE_LOGOS: Record<string, string> = {
  github:           `${SI}/github/181717`,
  vercel:           `${SI}/vercel/000000`,
  sendgrid:         `${SI}/sendgrid/009BDE`,
  gmail:            `${SI}/gmail/EA4335`,
  linkedin:         `${SI}/linkedin/0A66C2`,
  googlecalendar:   `${SI}/googlecalendar/4285F4`,
  google_calendar:  `${SI}/googlecalendar/4285F4`,
  notion:           `${SI}/notion/000000`,
  linear:           `${SI}/linear/5E6AD2`,
  product_tracker:  `${SI}/linear/5E6AD2`,
  instagram:        `${SI}/instagram/E4405F`,
  tiktok:           `${SI}/tiktok/000000`,
  meta_ads:         `${SI}/meta/0082FB`,
  slack:            `${SI}/slack/4A154B`,
  discord:          `${SI}/discord/5865F2`,
  google_drive:     `${SI}/googledrive/4285F4`,
  google_workspace: `${SI}/google/4285F4`,
  google_sheets:    `${SI}/googlesheets/34A853`,
  confluence:       `${SI}/confluence/172B4D`,
  zendesk:          `${SI}/zendesk/03363D`,
  helpdesk:         `${SI}/zendesk/03363D`,
  figma:            `${SI}/figma/F24E1E`,
  stripe:           `${SI}/stripe/635BFF`,
  supabase:         `${SI}/supabase/3FCF8E`,
  hubspot:          `${SI}/hubspot/FF7A59`,
  crm:              `${SI}/hubspot/FF7A59`,
  posthog:          `${SI}/posthog/000000`,
  analytics:        `${SI}/posthog/000000`,
  sentry:           `${SI}/sentry/362D59`,
  aws:              `${SI}/amazonaws/232F3E`,
};

export default function ServiceLogo({
  serviceKey,
  label,
  size = 24,
  fallback,
}: {
  serviceKey: string;
  label: string;
  size?: number;
  fallback?: string;
}) {
  const [err, setErr] = useState(false);
  const src = SERVICE_LOGOS[serviceKey];
  if (!src || err) {
    return (
      <div style={{
        width: size, height: size, flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: fallback ? size * 0.6 : size * 0.45,
        fontWeight: 700, color: "var(--fg-mute)",
        lineHeight: 1,
      }}>
        {fallback ?? label[0].toUpperCase()}
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={label}
      width={size}
      height={size}
      onError={() => setErr(true)}
      style={{ objectFit: "contain", flexShrink: 0, display: "block" }}
    />
  );
}
