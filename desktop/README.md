# Astra Desktop

This folder contains a thin Tauri desktop shell for the shared `frontend/` app.

## Why this setup

- Development loads `http://localhost:3000`, so normal Next.js edits still hot reload.
- Production loads the deployed `FRONTEND_URL`, so installed desktop builds pick up the latest server-deployed frontend without rebundling for routine UI changes.
- The hosted backend stays unchanged. Both web and desktop use the same API surface.

## Prerequisites

- Node.js and npm
- Rust and Cargo for running or building Tauri apps

## Commands

```bash
cd desktop
npm install
npm run dev
```

`npm run dev` will:

1. Read `FRONTEND_URL` from the environment or the repo `.env` files
2. Inject the repo-level env values into the frontend dev process so shared auth and backend settings work in desktop mode
3. Regenerate `src-tauri/tauri.conf.json`
4. Start the Next.js dev server from `../frontend`
5. Launch the Tauri desktop shell against `http://localhost:3000`

For production packaging:

```bash
cd desktop
npm install
npm run build
```

If the deployed frontend URL changes, update `FRONTEND_URL` in your environment or `.env` file and rerun the command.

## Public macOS releases

Public macOS downloads must be Apple-signed and notarized. A plain ad-hoc DMG may download successfully but can still be rejected by Gatekeeper as damaged or unsafe.

Public release policy:

- [Desktop Signing And Release](/Users/ishaangubbala/Documents/Astra/docs/Desktop_Release_Signing.md)

Detailed signing identities, CI secret names, and release-host configuration are intentionally kept out of tracked docs. Use the signed release workflow and local private operator notes when preparing a public build.
