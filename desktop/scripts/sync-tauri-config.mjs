import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");
const desktopDir = path.resolve(__dirname, "..");
const srcTauriDir = path.resolve(__dirname, "..", "src-tauri");
const bundledShellDir = path.join(desktopDir, ".generated-shell");

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
const frontendOrigin = frontendUrlObject.origin;
mkdirSync(bundledShellDir, { recursive: true });
writeFileSync(
  path.join(bundledShellDir, "index.html"),
  `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Astra Desktop</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; min-height: 100vh; display: grid; place-items: center; background: #0d1117; color: #f5f7fb; }
      main { width: min(520px, calc(100vw - 40px)); padding: 28px; border: 1px solid rgba(255,255,255,0.12); border-radius: 18px; background: rgba(255,255,255,0.04); }
      button { margin-top: 14px; padding: 10px 14px; border-radius: 10px; border: 0; background: #f5f7fb; color: #0d1117; cursor: pointer; }
      p { color: rgba(245,247,251,0.82); line-height: 1.5; }
    </style>
  </head>
  <body>
    <main>
      <h1>Astra is offline</h1>
      <p id="status">Trying to reach ${frontendUrl}…</p>
      <button id="retry" type="button">Retry</button>
    </main>
    <script>
      const target = ${JSON.stringify(frontendUrl)};
      const status = document.getElementById("status");
      async function boot() {
        status.textContent = "Trying to reach " + target + "…";
        try {
          await fetch(target, { method: "GET", mode: "no-cors", cache: "no-store" });
          window.location.replace(target);
        } catch (_) {
          status.textContent = "Astra's hosted app is unreachable right now. Check your connection or try again shortly.";
        }
      }
      document.getElementById("retry").addEventListener("click", boot);
      boot();
    </script>
  </body>
</html>
`,
  "utf8"
);
const generatedConfigRs = `pub const FRONTEND_ORIGIN: &str = ${JSON.stringify(frontendOrigin)};
pub const DEV_FRONTEND_ORIGIN: &str = "http://localhost:3000";
`;

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
    frontendDist: bundledShellDir,
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
        // Google blocks OAuth in embedded WebViews by detecting the WKWebView
        // user-agent. Override to a standard Chrome UA so sign-in completes.
        userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
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

writeFileSync(
  path.join(srcTauriDir, "src", "generated_config.rs"),
  generatedConfigRs,
  "utf8"
);

process.stdout.write(
  `Synced Tauri config for deployed frontend ${frontendUrl}\n`
);
