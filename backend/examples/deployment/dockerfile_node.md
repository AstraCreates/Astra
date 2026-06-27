---
title: Production Dockerfile + CI (Node / Next.js)
category: deployment
tags: deployment docker dockerfile ci github actions node nextjs build pipeline
applies_to: technical technical_infra web deployment ops
---

Copy-ready multi-stage Dockerfile + GitHub Actions CI for a Node/Next.js app.

## Dockerfile (multi-stage, small image)
```dockerfile
# ---- deps ----
FROM node:22-slim AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci --no-audit --no-fund

# ---- build ----
FROM node:22-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---- run ----
FROM node:22-slim AS run
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/package*.json ./
COPY --from=build /app/node_modules ./node_modules
EXPOSE 3000
CMD ["npm", "start"]
```

## .dockerignore
```
node_modules
.next
.git
.env*
npm-debug.log
```

## GitHub Actions CI (.github/workflows/ci.yml)
```yaml
name: ci
on:
  push: { branches: [main] }
  pull_request:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: npm }
      - run: npm ci --no-audit --no-fund
      - run: npm run lint --if-present
      - run: npm run build
      - run: npm test --if-present
```

Notes:
- `npm ci` (not `install`) for reproducible builds.
- Multi-stage keeps the runtime image small (no build deps shipped).
- For Vercel/Railway you usually don't need the Dockerfile — push and let the platform build.
