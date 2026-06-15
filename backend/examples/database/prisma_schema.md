---
title: Prisma Schema — SaaS Starter (Users, Orgs, Subscriptions)
tags: [prisma, schema, database, postgresql, saas, users, subscriptions, next.js]
category: database
applies_to: [technical, technical_scaffold, technical_data, ops]
---

# Prisma SaaS Schema

Production-ready schema: users, orgs, subscriptions, API keys.

## `prisma/schema.prisma`
```prisma
generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model User {
  id            String    @id @default(cuid())
  email         String    @unique
  name          String?
  image         String?
  createdAt     DateTime  @default(now())
  updatedAt     DateTime  @updatedAt

  // Stripe
  stripeCustomerId String?  @unique

  // Auth (NextAuth)
  accounts      Account[]
  sessions      Session[]

  // App data
  memberships   Membership[]
  apiKeys       ApiKey[]
}

model Account {
  id                String  @id @default(cuid())
  userId            String
  type              String
  provider          String
  providerAccountId String
  refresh_token     String? @db.Text
  access_token      String? @db.Text
  expires_at        Int?
  token_type        String?
  scope             String?
  id_token          String? @db.Text

  user User @relation(fields: [userId], references: [id], onDelete: Cascade)

  @@unique([provider, providerAccountId])
}

model Session {
  id           String   @id @default(cuid())
  sessionToken String   @unique
  userId       String
  expires      DateTime
  user         User     @relation(fields: [userId], references: [id], onDelete: Cascade)
}

model Org {
  id        String   @id @default(cuid())
  name      String
  slug      String   @unique
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt

  memberships  Membership[]
  subscription Subscription?
  apiKeys      ApiKey[]
}

model Membership {
  id     String @id @default(cuid())
  role   Role   @default(MEMBER)
  userId String
  orgId  String

  user User @relation(fields: [userId], references: [id], onDelete: Cascade)
  org  Org  @relation(fields: [orgId], references: [id], onDelete: Cascade)

  createdAt DateTime @default(now())

  @@unique([userId, orgId])
}

enum Role {
  OWNER
  ADMIN
  MEMBER
}

model Subscription {
  id                   String             @id @default(cuid())
  orgId                String             @unique
  stripeSubscriptionId String             @unique
  stripePriceId        String
  status               SubscriptionStatus @default(INACTIVE)
  currentPeriodStart   DateTime?
  currentPeriodEnd     DateTime?
  cancelAtPeriodEnd    Boolean            @default(false)
  createdAt            DateTime           @default(now())
  updatedAt            DateTime           @updatedAt

  org Org @relation(fields: [orgId], references: [id], onDelete: Cascade)
}

enum SubscriptionStatus {
  ACTIVE
  INACTIVE
  PAST_DUE
  CANCELED
  TRIALING
}

model ApiKey {
  id        String    @id @default(cuid())
  name      String
  keyHash   String    @unique  // SHA-256 of the actual key — never store plaintext
  prefix    String             // First 8 chars shown to user: "sk_live_ab12cd34..."
  orgId     String?
  userId    String?
  lastUsed  DateTime?
  expiresAt DateTime?
  createdAt DateTime  @default(now())

  org  Org?  @relation(fields: [orgId], references: [id], onDelete: Cascade)
  user User? @relation(fields: [userId], references: [id], onDelete: Cascade)
}
```

## Setup
```bash
npm install prisma @prisma/client
npx prisma init --datasource-provider postgresql
# edit schema, then:
npx prisma migrate dev --name init
npx prisma generate
```

## `lib/db.ts`
```typescript
import { PrismaClient } from "@prisma/client";

const globalForPrisma = globalThis as unknown as { prisma: PrismaClient };

export const prisma =
  globalForPrisma.prisma ??
  new PrismaClient({
    log: process.env.NODE_ENV === "development" ? ["query", "error", "warn"] : ["error"],
  });

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma;
```

## Common queries
```typescript
// Create user + org on first sign-in
async function provisionNewUser(email: string, name: string) {
  return await prisma.$transaction(async (tx) => {
    const user = await tx.user.create({ data: { email, name } });
    const slug = email.split("@")[0].toLowerCase().replace(/[^a-z0-9]/g, "-");
    const org = await tx.org.create({ data: { name: `${name}'s workspace`, slug } });
    await tx.membership.create({ data: { userId: user.id, orgId: org.id, role: "OWNER" } });
    return { user, org };
  });
}

// Check subscription status
async function isSubscribed(orgId: string): Promise<boolean> {
  const sub = await prisma.subscription.findUnique({
    where: { orgId },
    select: { status: true },
  });
  return sub?.status === "ACTIVE" || sub?.status === "TRIALING";
}

// Verify API key
async function verifyApiKey(rawKey: string) {
  const { createHash } = await import("crypto");
  const hash = createHash("sha256").update(rawKey).digest("hex");
  return prisma.apiKey.findUnique({
    where: { keyHash: hash },
    include: { org: true, user: true },
  });
}
```

## Required env vars
```
DATABASE_URL=postgresql://user:password@host:5432/dbname?sslmode=require
```

## Notes
- Run `npx prisma migrate deploy` in CI/CD, NOT `migrate dev` (dev creates migration files)
- Supabase: use the **pooler** connection string for serverless (port 6543), direct for migrations
- Never store raw API keys — hash with SHA-256, show the prefix to the user on creation
- `@db.Text` on token fields prevents 191-char MySQL limit (not needed for Postgres but harmless)
