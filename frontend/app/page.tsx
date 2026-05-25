"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { submitGoal } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [instruction, setInstruction] = useState("");
  const [founderId, setFounderId] = useState("founder_001");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!instruction.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await submitGoal(founderId, instruction);
      router.push(`/goal/${result.session_id}?instruction=${encodeURIComponent(instruction)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit goal");
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-12">
      <div className="flex flex-col gap-3">
        <h1 className="text-4xl font-bold tracking-tight text-white">
          What are you building?
        </h1>
        <p className="text-zinc-400 text-lg">
          Describe your startup idea. Astra will research the market, build your landing page, scaffold your product, handle legal, and launch marketing — autonomously.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="e.g. Build a SaaS platform that helps indie hackers track their MRR across multiple products with Stripe webhooks..."
          rows={5}
          className="w-full rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-3 text-zinc-100 placeholder-zinc-500 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none text-base"
          disabled={loading}
        />

        <div className="flex items-center gap-3">
          <label className="text-zinc-400 text-sm whitespace-nowrap">Founder ID</label>
          <input
            value={founderId}
            onChange={(e) => setFounderId(e.target.value)}
            className="flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-300 text-sm focus:border-violet-500 focus:outline-none"
            placeholder="founder_001"
          />
        </div>

        {error && (
          <p className="text-red-400 text-sm rounded-lg bg-red-950/30 border border-red-800 px-4 py-2">
            {error}
          </p>
        )}

        <div className="flex gap-3">
          <button
            type="submit"
            disabled={loading || !instruction.trim()}
            className="rounded-xl bg-violet-600 px-6 py-3 font-semibold text-white hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Launching agents…" : "Launch Astra →"}
          </button>
          <a
            href="/setup"
            className="rounded-xl border border-zinc-700 px-6 py-3 font-semibold text-zinc-300 hover:border-zinc-500 hover:text-white transition-colors"
          >
            Connect Accounts
          </a>
        </div>
      </form>

      <div className="grid grid-cols-3 gap-4 border-t border-zinc-800 pt-8">
        {[
          { icon: "🔬", label: "Market Research", desc: "TAM/SAM/SOM, patents, competitors" },
          { icon: "🌐", label: "Landing Page", desc: "Deploy to Vercel in minutes" },
          { icon: "📢", label: "Marketing", desc: "Instagram Reels, TikTok, Meta Ads" },
          { icon: "⚙️", label: "Technical", desc: "GitHub scaffold, architecture" },
          { icon: "⚖️", label: "Legal", desc: "LLC formation, privacy policy" },
          { icon: "🚀", label: "Fundraising", desc: "Investor intel, accelerators" },
        ].map((item) => (
          <div key={item.label} className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 flex flex-col gap-2">
            <span className="text-2xl">{item.icon}</span>
            <p className="font-semibold text-zinc-200 text-sm">{item.label}</p>
            <p className="text-zinc-500 text-xs">{item.desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
