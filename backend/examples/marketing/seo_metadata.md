---
title: Next.js 15 SEO Metadata — Open Graph, Twitter Card, Structured Data
tags: [seo, metadata, opengraph, twitter, next.js, schema.org]
category: marketing
applies_to: [marketing_seo, web, technical, technical_scaffold]
---

# Next.js 15 SEO Metadata

## Static metadata `app/layout.tsx`
```typescript
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: {
    default: "Astra — AI Operating System for Founders",
    template: "%s | Astra",
  },
  description: "Run your entire startup with AI agents — product, marketing, sales, legal, ops.",
  keywords: ["AI startup tools", "founder OS", "AI agents"],
  authors: [{ name: "Astra" }],
  creator: "Astra",
  metadataBase: new URL("https://yourdomain.com"),
  openGraph: {
    type: "website",
    siteName: "Astra",
    title: "Astra — AI Operating System for Founders",
    description: "Run your entire startup with AI agents.",
    url: "https://yourdomain.com",
    images: [{ url: "/og.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Astra — AI Operating System for Founders",
    description: "Run your entire startup with AI agents.",
    images: ["/og.png"],
    creator: "@yourtwitterhandle",
  },
  robots: { index: true, follow: true },
};
```

## Dynamic metadata (per page)
```typescript
// app/blog/[slug]/page.tsx
import type { Metadata } from "next";

export async function generateMetadata({ params }: { params: { slug: string } }): Promise<Metadata> {
  const post = await getPost(params.slug);
  return {
    title: post.title,
    description: post.excerpt,
    openGraph: {
      title: post.title,
      description: post.excerpt,
      images: [{ url: post.coverImage }],
    },
  };
}
```

## Structured data (JSON-LD)
```typescript
// In a server component or layout
export default function Page() {
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "Astra",
    applicationCategory: "BusinessApplication",
    description: "AI operating system for founders",
    offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  };
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      {/* page content */}
    </>
  );
}
```

## Sitemap `app/sitemap.ts`
```typescript
import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: "https://yourdomain.com", lastModified: new Date(), changeFrequency: "weekly", priority: 1 },
    { url: "https://yourdomain.com/pricing", lastModified: new Date(), changeFrequency: "monthly", priority: 0.8 },
  ];
}
```

## OG image `app/opengraph-image.tsx`
```typescript
import { ImageResponse } from "next/og";

export const runtime = "edge";
export const size = { width: 1200, height: 630 };

export default async function Image() {
  return new ImageResponse(
    <div style={{ background: "#0f172a", width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <h1 style={{ color: "white", fontSize: 72, fontWeight: 700 }}>Astra</h1>
    </div>
  );
}
```

## Notes
- Place OG image at `/public/og.png` (1200×630px)
- `metadataBase` is required for relative image URLs to resolve correctly
- JSON-LD structured data is not required but improves rich snippets in Google
