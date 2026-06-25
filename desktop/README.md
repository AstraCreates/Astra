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

Release guide:

- [Desktop Signing And Release](/Users/ishaangubbala/Documents/Astra/docs/Desktop_Release_Signing.md)

GitHub Actions workflow:

- [release-desktop-signed.yml](/Users/ishaangubbala/Documents/Astra/.github/workflows/release-desktop-signed.yml)

The workflow is intended for the DMG that backs the public desktop download link. It validates signing inputs, builds the desktop app, verifies the resulting `.app` is not ad-hoc signed, verifies notarization, and uploads the DMG plus checksum to the chosen GitHub release.
