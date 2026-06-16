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
2. Regenerate `src-tauri/tauri.conf.json`
3. Start the Next.js dev server from `../frontend`
4. Launch the Tauri desktop shell against `http://localhost:3000`

For production packaging:

```bash
cd desktop
npm install
npm run build
```

If the deployed frontend URL changes, update `FRONTEND_URL` in your environment or `.env` file and rerun the command.
