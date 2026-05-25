"use client";

import { useState, useEffect, useCallback } from "react";
import { saveServiceCredential, getComposioOAuthUrls, getSetupStatus, SetupStatus } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const STEPS = [
  { id: "founder", label: "Founder ID" },
  { id: "github", label: "GitHub" },
  { id: "sendgrid", label: "SendGrid" },
  { id: "vercel", label: "Vercel" },
  { id: "composio", label: "Composio" },
  { id: "done", label: "Done" },
];

const COMPOSIO_APPS = [
  { key: "gmail", label: "Gmail", icon: "📧", desc: "Send from your inbox" },
  { key: "linkedin", label: "LinkedIn", icon: "💼", desc: "Post announcements" },
  { key: "twitter", label: "Twitter/X", icon: "🐦", desc: "Tweet launches (requires custom OAuth app)" },
  { key: "googlecalendar", label: "Calendar", icon: "📅", desc: "Schedule meetings" },
  { key: "notion", label: "Notion", icon: "📝", desc: "Update wiki" },
  { key: "linear", label: "Linear", icon: "📋", desc: "Track dev issues" },
  { key: "github", label: "GitHub PRs", icon: "🔀", desc: "Open PRs & issues" },
];

interface StepConfig {
  service: string;
  credKey: string;
  title: string;
  description: string;
  placeholder: string;
  createUrl: string;
  createLabel: string;
  instructions: string[];
}

const SERVICE_STEPS: StepConfig[] = [
  {
    service: "github",
    credKey: "token",
    title: "GitHub Personal Access Token",
    description: "Astra uses this to scaffold repos, push code, and open PRs on your behalf.",
    placeholder: "ghp_xxxxxxxxxxxxxxxxxxxx",
    createUrl: "https://github.com/settings/tokens/new?description=Astra+Automation&scopes=repo,workflow,write:packages",
    createLabel: "Create token on GitHub →",
    instructions: [
      "Click the link below to open GitHub token settings",
      "Set expiration to \"No expiration\" (or 1 year)",
      "Check: repo, workflow, write:packages",
      "Click Generate token, copy it here",
    ],
  },
  {
    service: "sendgrid",
    credKey: "api_key",
    title: "SendGrid API Key",
    description: "Astra uses this to send email campaigns from your SendGrid account.",
    placeholder: "SG.xxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    createUrl: "https://app.sendgrid.com/settings/api_keys",
    createLabel: "Create key on SendGrid →",
    instructions: [
      "Sign in or create a free SendGrid account",
      "Go to Settings → API Keys → Create API Key",
      "Choose Full Access",
      "Copy the key and paste it here",
    ],
  },
  {
    service: "vercel",
    credKey: "token",
    title: "Vercel Deploy Token",
    description: "Astra uses this to deploy your landing page and app to Vercel.",
    placeholder: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    createUrl: "https://vercel.com/account/tokens",
    createLabel: "Create token on Vercel →",
    instructions: [
      "Sign in or create a free Vercel account",
      "Go to Account → Tokens → Create",
      "Name it \"Astra Deploy\", no expiry",
      "Copy the token and paste it here",
    ],
  },
];

export default function SetupPage() {
  const [step, setStep] = useState(0);
  const [founderId, setFounderId] = useState("founder_001");
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [composioUrls, setComposioUrls] = useState<Record<string, string> | null>(null);
  const [composioLoading, setComposioLoading] = useState(false);
  const [status, setStatus] = useState<SetupStatus | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const s = await getSetupStatus(founderId);
      setStatus(s);
    } catch {
      // founder may not exist yet
    }
  }, [founderId]);

  useEffect(() => {
    if (step === STEPS.length - 1) fetchStatus();
  }, [step, fetchStatus]);

  async function handleFounderNext() {
    if (!founderId.trim()) return;
    setStep(1);
  }

  async function handleServiceSave(cfg: StepConfig) {
    const val = inputs[cfg.service]?.trim();
    if (!val) { setError("Paste your " + cfg.title + " to continue."); return; }
    setSaving(true);
    setError(null);
    try {
      await saveServiceCredential(founderId, cfg.service, { [cfg.credKey]: val });
      setStep((s) => s + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleSkip() {
    setStep((s) => s + 1);
    setError(null);
  }

  async function loadComposioUrls() {
    setComposioLoading(true);
    setError(null);
    try {
      const urls = await getComposioOAuthUrls(founderId);
      setComposioUrls(urls);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load OAuth URLs");
    } finally {
      setComposioLoading(false);
    }
  }

  const currentStepId = STEPS[step]?.id;

  return (
    <div className="flex flex-col gap-8 max-w-xl">
      {/* Progress bar */}
      <div className="flex flex-col gap-3">
        <h1 className="text-3xl font-bold text-white">Connect Accounts</h1>
        <div className="flex gap-1.5 items-center">
          {STEPS.map((s, i) => (
            <div key={s.id} className="flex items-center gap-1.5">
              <div
                className={`h-2 rounded-full transition-all ${
                  i < step
                    ? "bg-green-500 w-6"
                    : i === step
                    ? "bg-violet-500 w-8"
                    : "bg-zinc-700 w-4"
                }`}
              />
              {i < STEPS.length - 1 && <div className="h-px w-2 bg-zinc-700" />}
            </div>
          ))}
          <span className="ml-2 text-zinc-500 text-xs">{STEPS[step].label}</span>
        </div>
      </div>

      {/* Step: Founder ID */}
      {currentStepId === "founder" && (
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <h2 className="text-xl font-semibold text-white">Who are you?</h2>
            <p className="text-zinc-400 text-sm">
              Credentials are stored encrypted per founder ID. Use the same ID everywhere in Astra.
            </p>
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-zinc-400 text-xs font-semibold uppercase tracking-wide">Founder ID</label>
            <input
              value={founderId}
              onChange={(e) => setFounderId(e.target.value)}
              className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-zinc-200 text-sm focus:border-violet-500 focus:outline-none"
              placeholder="founder_001"
              onKeyDown={(e) => e.key === "Enter" && handleFounderNext()}
            />
          </div>
          <button
            onClick={handleFounderNext}
            disabled={!founderId.trim()}
            className="self-start rounded-xl bg-violet-600 px-6 py-3 font-semibold text-white hover:bg-violet-500 disabled:opacity-50 transition-colors"
          >
            Start setup →
          </button>
        </div>
      )}

      {/* Steps: GitHub / SendGrid / Vercel */}
      {SERVICE_STEPS.map((cfg, i) => {
        if (currentStepId !== cfg.service) return null;
        return (
          <div key={cfg.service} className="flex flex-col gap-6">
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono text-violet-400 bg-violet-950/40 border border-violet-800 rounded px-2 py-0.5">
                  Step {i + 2} of {STEPS.length}
                </span>
              </div>
              <h2 className="text-xl font-semibold text-white">{cfg.title}</h2>
              <p className="text-zinc-400 text-sm">{cfg.description}</p>
            </div>

            <ol className="flex flex-col gap-2 border border-zinc-800 rounded-xl p-4 bg-zinc-900/40">
              {cfg.instructions.map((inst, j) => (
                <li key={j} className="flex gap-3 text-sm text-zinc-300">
                  <span className="text-zinc-600 font-mono w-4 shrink-0">{j + 1}.</span>
                  {inst}
                </li>
              ))}
            </ol>

            <a
              href={cfg.createUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="self-start text-sm text-violet-400 hover:text-violet-300 underline underline-offset-2"
            >
              {cfg.createLabel}
            </a>

            <div className="flex flex-col gap-2">
              <label className="text-zinc-400 text-xs font-semibold uppercase tracking-wide">
                Paste {cfg.title}
              </label>
              <input
                value={inputs[cfg.service] ?? ""}
                onChange={(e) => setInputs((p) => ({ ...p, [cfg.service]: e.target.value }))}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2.5 text-zinc-200 text-sm font-mono focus:border-violet-500 focus:outline-none"
                placeholder={cfg.placeholder}
                onKeyDown={(e) => e.key === "Enter" && handleServiceSave(cfg)}
              />
            </div>

            {error && (
              <p className="text-red-400 text-sm rounded-lg bg-red-950/30 border border-red-800 px-4 py-2">
                {error}
              </p>
            )}

            <div className="flex gap-3">
              <button
                onClick={() => handleServiceSave(cfg)}
                disabled={saving || !inputs[cfg.service]?.trim()}
                className="rounded-xl bg-violet-600 px-6 py-3 font-semibold text-white hover:bg-violet-500 disabled:opacity-50 transition-colors"
              >
                {saving ? "Saving…" : "Save & continue →"}
              </button>
              <button
                onClick={handleSkip}
                disabled={saving}
                className="rounded-xl border border-zinc-700 px-5 py-3 text-sm text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 transition-colors"
              >
                Skip for now
              </button>
            </div>
          </div>
        );
      })}

      {/* Step: Composio OAuth */}
      {currentStepId === "composio" && (
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-violet-400 bg-violet-950/40 border border-violet-800 rounded px-2 py-0.5">
                Step 5 of {STEPS.length}
              </span>
            </div>
            <h2 className="text-xl font-semibold text-white">Connect your accounts</h2>
            <p className="text-zinc-400 text-sm">
              Astra uses Composio to act on your behalf — send emails from Gmail, post to LinkedIn, tweet, manage calendar, Notion, and Linear. First paste your Composio API key, then authorize each service.
            </p>
          </div>

          {/* Composio API key entry */}
          <div className="flex flex-col gap-3 border border-zinc-800 rounded-xl p-4 bg-zinc-900/40">
            <div className="flex flex-col gap-1">
              <p className="text-zinc-200 text-sm font-semibold">Composio API Key</p>
              <p className="text-zinc-500 text-xs">
                Free at{" "}
                <a href="https://app.composio.dev/settings" target="_blank" rel="noopener noreferrer" className="text-violet-400 hover:underline">
                  app.composio.dev/settings
                </a>
              </p>
            </div>
            <div className="flex gap-2">
              <input
                value={inputs["composio_api_key"] ?? ""}
                onChange={(e) => setInputs((p) => ({ ...p, composio_api_key: e.target.value }))}
                className="flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-200 text-sm font-mono focus:border-violet-500 focus:outline-none"
                placeholder="api_key_..."
              />
              <button
                onClick={async () => {
                  const key = inputs["composio_api_key"]?.trim();
                  if (!key) return;
                  setSaving(true);
                  setError(null);
                  try {
                    await saveServiceCredential(founderId, "composio", { api_key: key });
                    setSaving(false);
                  } catch (e) {
                    setError(e instanceof Error ? e.message : "Save failed");
                    setSaving(false);
                  }
                }}
                disabled={saving || !inputs["composio_api_key"]?.trim()}
                className="rounded-lg bg-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-600 disabled:opacity-50 transition-colors whitespace-nowrap"
              >
                {saving ? "Saving…" : "Save key"}
              </button>
            </div>
          </div>

          {(!composioUrls || Object.values(composioUrls).every(v => String(v).startsWith("error"))) ? (
            <button
              onClick={loadComposioUrls}
              disabled={composioLoading}
              className="self-start rounded-xl bg-violet-600 px-6 py-3 font-semibold text-white hover:bg-violet-500 disabled:opacity-50 transition-colors"
            >
              {composioLoading ? "Loading OAuth links…" : composioUrls ? "Retry loading links →" : "Load OAuth links →"}
            </button>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {COMPOSIO_APPS.map((app) => {
                const url = composioUrls[app.key];
                const isError = !url || url.startsWith("error:");
                return (
                  <a
                    key={app.key}
                    href={isError ? undefined : url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`rounded-xl border p-4 flex items-center gap-3 transition-colors ${
                      isError
                        ? "border-zinc-800 bg-zinc-900/30 opacity-40 cursor-not-allowed"
                        : "border-violet-800 bg-violet-950/20 hover:border-violet-600 hover:bg-violet-950/40"
                    }`}
                    onClick={isError ? (e) => e.preventDefault() : undefined}
                  >
                    <span className="text-xl">{app.icon}</span>
                    <div className="flex flex-col gap-0.5 min-w-0">
                      <p className="font-semibold text-zinc-200 text-sm">{app.label}</p>
                      <p className="text-zinc-500 text-xs truncate">{app.desc}</p>
                    </div>
                    {!isError && (
                      <span className="ml-auto text-violet-400 text-xs whitespace-nowrap">Connect →</span>
                    )}
                  </a>
                );
              })}
            </div>
          )}

          {error && (
            <p className="text-red-400 text-sm rounded-lg bg-red-950/30 border border-red-800 px-4 py-2">
              {error}
            </p>
          )}

          <div className="flex gap-3 pt-2">
            <button
              onClick={() => setStep((s) => s + 1)}
              className="rounded-xl bg-violet-600 px-6 py-3 font-semibold text-white hover:bg-violet-500 transition-colors"
            >
              Finish setup →
            </button>
            <button
              onClick={handleSkip}
              className="rounded-xl border border-zinc-700 px-5 py-3 text-sm text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 transition-colors"
            >
              Skip for now
            </button>
          </div>
        </div>
      )}

      {/* Step: Done */}
      {currentStepId === "done" && (
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <h2 className="text-xl font-semibold text-white">Setup complete</h2>
            <p className="text-zinc-400 text-sm">
              Astra is ready. You can connect more services anytime by returning to this page.
            </p>
          </div>

          {status && (
            <div className="grid grid-cols-3 gap-3">
              {(
                [
                  { key: "github", label: "GitHub", icon: "🐙" },
                  { key: "sendgrid", label: "SendGrid", icon: "✉️" },
                  { key: "vercel", label: "Vercel", icon: "▲" },
                  { key: "instagram", label: "Instagram", icon: "📸" },
                  { key: "tiktok", label: "TikTok", icon: "🎵" },
                  { key: "meta_ads", label: "Meta Ads", icon: "📢" },
                ] as Array<{ key: keyof SetupStatus; label: string; icon: string }>
              ).map((svc) => {
                const connected = status[svc.key];
                return (
                  <div
                    key={svc.key}
                    className={`rounded-xl border p-4 flex flex-col gap-2 ${
                      connected ? "border-green-800 bg-green-950/20" : "border-zinc-800 bg-zinc-900/40"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xl">{svc.icon}</span>
                      <span className={`text-xs font-mono ${connected ? "text-green-400" : "text-zinc-600"}`}>
                        {connected ? "✓" : "–"}
                      </span>
                    </div>
                    <p className="font-semibold text-zinc-200 text-sm">{svc.label}</p>
                  </div>
                );
              })}
            </div>
          )}

          <div className="flex gap-3 flex-wrap">
            <a
              href="/"
              className="rounded-xl bg-violet-600 px-6 py-3 font-semibold text-white hover:bg-violet-500 transition-colors"
            >
              Launch a goal →
            </a>
            <button
              onClick={() => { setStep(1); setError(null); }}
              className="rounded-xl border border-zinc-700 px-5 py-3 text-sm text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 transition-colors"
            >
              Add more services
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
