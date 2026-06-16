import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");
const desktopDir = path.resolve(__dirname, "..");
const srcTauriDir = path.resolve(__dirname, "..", "src-tauri");
const frontendDir = path.join(repoRoot, "frontend");

function parseEnvFile(filePath) {
  try {
    const raw = readFileSync(filePath, "utf8");
    const values = {};
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) {
        continue;
      }
      const idx = trimmed.indexOf("=");
      if (idx === -1) {
        continue;
      }
      const key = trimmed.slice(0, idx).trim();
      const value = trimmed.slice(idx + 1).trim();
      values[key] = value;
    }
    return values;
  } catch {
    return {};
  }
}

function getFrontendUrl() {
  const envSources = [
    process.env,
    parseEnvFile(path.join(repoRoot, ".env.server")),
    parseEnvFile(path.join(repoRoot, ".env")),
    parseEnvFile(path.join(repoRoot, ".env.example")),
  ];

  for (const source of envSources) {
    const value = source.FRONTEND_URL;
    if (value) {
      return value.replace(/\/+$/, "");
    }
  }

  throw new Error(
    "Unable to resolve FRONTEND_URL. Set it in the environment or one of the repo .env files before running desktop scripts."
  );
}

const frontendUrl = getFrontendUrl();
const frontendUrlObject = new URL(frontendUrl);
const frontendOriginPattern = `${frontendUrlObject.origin}/*`;

const tauriConfig = {
  $schema: "https://schema.tauri.app/config/2",
  productName: "Astra Desktop",
  version: "0.1.0",
  identifier: "com.astracreates.desktop",
  build: {
    beforeDevCommand: {
      cwd: desktopDir,
      script: "node ./scripts/run-frontend-dev.mjs",
      wait: false,
    },
    devUrl: "http://localhost:3000",
    frontendDist: frontendUrl,
  },
  app: {
    security: {
      csp: null,
    },
    windows: [
      {
        label: "main",
        title: "Astra",
        width: 1440,
        height: 960,
        minWidth: 1100,
        minHeight: 760,
        resizable: true,
        maximized: false,
      },
    ],
  },
  bundle: {
    active: true,
    icon: ["icons/icon.icns", "icons/icon.png"],
    targets: "all",
    shortDescription: "Desktop shell for the Astra web app",
    longDescription:
      "Astra Desktop wraps the shared Astra frontend in a native Tauri shell while continuing to use the hosted Astra backend and deployed frontend.",
    createUpdaterArtifacts: false,
    macOS: {
      exceptionDomain: frontendUrlObject.protocol === "http:" ? frontendUrlObject.hostname : null,
    },
  },
};

const capability = {
  $schema: "../gen/schemas/desktop-schema.json",
  identifier: "default",
  description:
    "Allows the Astra frontend to access the default Tauri API surface from trusted Astra origins.",
  windows: ["main"],
  remote: {
    urls: [frontendOriginPattern, "http://localhost:3000/*"],
  },
  permissions: ["core:default"],
};

writeFileSync(
  path.join(srcTauriDir, "tauri.conf.json"),
  `${JSON.stringify(tauriConfig, null, 2)}\n`,
  "utf8"
);

writeFileSync(
  path.join(srcTauriDir, "capabilities", "default.json"),
  `${JSON.stringify(capability, null, 2)}\n`,
  "utf8"
);

process.stdout.write(
  `Synced Tauri config for deployed frontend ${frontendUrl}\n`
);
