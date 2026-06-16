import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..", "..");
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

const mergedEnv = {
  ...parseEnvFile(path.join(repoRoot, ".env.example")),
  ...parseEnvFile(path.join(repoRoot, ".env")),
  ...parseEnvFile(path.join(repoRoot, ".env.server")),
  ...process.env,
};

mergedEnv.FRONTEND_URL = process.env.FRONTEND_URL ?? "http://localhost:3000";
mergedEnv.NEXTAUTH_URL = process.env.NEXTAUTH_URL ?? mergedEnv.FRONTEND_URL;

const child = spawn("npm", ["run", "dev"], {
  cwd: frontendDir,
  env: mergedEnv,
  stdio: "inherit",
});

const forwardSignal = (signal) => {
  if (!child.killed) {
    child.kill(signal);
  }
};

process.on("SIGINT", () => forwardSignal("SIGINT"));
process.on("SIGTERM", () => forwardSignal("SIGTERM"));

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
