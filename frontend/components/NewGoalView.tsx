"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getStacks, submitGoal, ingestAttachment, type AgentStackTemplate, type TechnicalScope, type ResearchDepth, type MarketingChannels } from "@/lib/api";
import { useDevUser } from "@/lib/use-dev-user";
import BusinessQuizModal, { type QuizResult, STACK_MAP, BIZ_TYPES } from "@/components/BusinessQuizModal";

export default function NewGoalView() {
  const router = useRouter();
  const { userId } = useDevUser();
  const [stacks, setStacks] = useState<AgentStackTemplate[]>([]);
  const [stackHint, setStackHint] = useState("Loading stacks…");
  const [selStack, setSelStack] = useState<string>("");
  const [technicalScope, setTechnicalScope] = useState<TechnicalScope>("both");
  const [researchDepth, setResearchDepth] = useState<ResearchDepth | "">("");
  const [marketingChannels, setMarketingChannels] = useState<MarketingChannels>("both");
  const [chars, setChars] = useState(0);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachments, setAttachments] = useState<{ name: string; content: string }[]>([]);
  const [uploading, setUploading] = useState(false);
  const [company, setCompany] = useState("");
  const [showQuiz, setShowQuiz] = useState(false);
  const [quizResult, setQuizResult] = useState<QuizResult | null>(null);
  // Existing business context
  const [showExisting, setShowExisting] = useState(false);
  const [exGithub, setExGithub] = useState("");
  const [exUrl, setExUrl] = useState("");
  const [exRevenue, setExRevenue] = useState("");
  const [exUsers, setExUsers] = useState("");
  const [exAge, setExAge] = useState("");
  const [exRefs, setExRefs] = useState<string[]>([""]);
  const displayCompany = company;
  const goalRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setCompany(localStorage.getItem("astra_onboarding_company") || "");
      // Pre-fill from dashboard button tile
      const prefill = sessionStorage.getItem("astra_prefill_goal");
      if (prefill && goalRef.current) {
        goalRef.current.value = prefill;
        setChars(prefill.length);
        try { sessionStorage.removeItem("astra_prefill_goal"); } catch {}
      }
    }
    getStacks().then((s) => {
      setStacks(s);
      // Pre-select stack from onboarding if set
      const savedStack = typeof window !== "undefined" ? localStorage.getItem("astra_onboarding_stack") || "" : "";
      if (savedStack) setSelStack(savedStack);
      setStackHint(s.length ? `${s.length} stack${s.length > 1 ? "s" : ""} available` : "Using auto-select");
    }).catch(() => setStackHint("Could not load stacks — auto will be used"));
  }, []);

  const onFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    for (const f of Array.from(files)) {
      try {
        const r = await ingestAttachment(userId, f, true);
        if (r.content) setAttachments((prev) => [...prev, { name: r.filename || f.name, content: r.content }]);
        else if (r.error) setErr(`⚠ ${f.name}: ${r.error}`);
      } catch (e) { setErr(`⚠ ${f.name}: ${e instanceof Error ? e.message : String(e)}`); }
    }
    setUploading(false);
  };

  const buildExistingBlock = (): string => {
    if (!showExisting) return "";
    const lines: string[] = ["Existing business context:"];
    if (exGithub.trim()) lines.push(`GitHub repo: ${exGithub.trim()}`);
    if (exUrl.trim()) lines.push(`Live site: ${exUrl.trim()}`);
    if (exRevenue.trim()) lines.push(`Current MRR / revenue: ${exRevenue.trim()}`);
    if (exUsers.trim()) lines.push(`Current users / customers: ${exUsers.trim()}`);
    if (exAge.trim()) lines.push(`Time in market: ${exAge.trim()}`);
    const validRefs = exRefs.filter((r) => r.trim());
    if (validRefs.length) lines.push(`References / inspirations: ${validRefs.join(", ")}`);
    return lines.length > 1 ? lines.join("\n") : "";
  };

  const doLaunch = async (quiz: QuizResult | null) => {
    const goal = goalRef.current?.value.trim() || "";
    setErr("");
    if (goal.length < 10) { setErr("⚠ Please describe your goal in more detail (min 10 chars)."); return; }
    setBusy(true);
    try {
      let instruction = displayCompany ? `Company/project name: ${displayCompany}\n\n${goal}` : goal;
      if (quiz) instruction = `${instruction}\n\n---\n${quiz.contextBlock}`;
      const existingBlock = buildExistingBlock();
      if (existingBlock) instruction = `${instruction}\n\n---\n${existingBlock}`;
      if (attachments.length) {
        instruction += "\n\nAttached context:\n" + attachments.map((a) => `--- ${a.name} ---\n${a.content.slice(0, 8000)}`).join("\n\n");
      }
      const stackId = selStack || (quiz?.businessType ? STACK_MAP[quiz.businessType] : "") || "idea_to_revenue";
      const data = await submitGoal(userId, instruction, {}, stackId, {
        technicalScope,
        researchDepth: researchDepth || undefined,
        marketingChannels,
      });
      if (!data.session_id) throw new Error("No session_id returned");
      window.location.assign(`/s/${data.session_id}`);
    } catch (e) {
      setBusy(false);
      setErr(`⚠ ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const submit = () => {
    const goal = goalRef.current?.value.trim() || "";
    if (goal.length < 10) { setErr("⚠ Please describe your goal in more detail (min 10 chars)."); return; }
    if (!quizResult && !selStack) { setShowQuiz(true); return; }
    doLaunch(quizResult);
  };

  const onQuizComplete = (result: QuizResult) => { setQuizResult(result); setShowQuiz(false); doLaunch(result); };
  const onQuizSkip = () => { setShowQuiz(false); doLaunch(null); };

  return (
    <div style={{ flex: 1, overflowY: "auto" }}>
      {showQuiz && <BusinessQuizModal onComplete={onQuizComplete} onSkip={onQuizSkip} />}
      <div className="new-wrap new-wrap-wide">
        {displayCompany && (
          <div style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "4px 10px", borderRadius: 20, border: "1px solid var(--bd)", background: "var(--surface)", fontSize: 10.5, color: "var(--fd)", marginBottom: 16 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--blue)" }} />
            <span style={{ fontWeight: 600, color: "var(--fg)" }}>{displayCompany}</span>
          </div>
        )}
        {quizResult && (
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "4px 10px", borderRadius: 20, border: "1px solid var(--blue, #3b82f6)", background: "rgba(59,130,246,0.08)", fontSize: 10.5, marginBottom: 16, marginLeft: displayCompany ? 8 : 0 }}>
            <span style={{ fontWeight: 600, color: "var(--fg)" }}>{BIZ_TYPES.find(t => t.id === quizResult.businessType)?.label ?? quizResult.businessType}</span>
            {quizResult.subCategory && <span style={{ color: "var(--fm)" }}>· {quizResult.subCategory}</span>}
            <span style={{ color: "var(--fm)" }}>· {quizResult.stage}</span>
            <button onClick={() => setQuizResult(null)} style={{ fontSize: 10, color: "var(--fm)", background: "none", border: "none", cursor: "pointer", padding: 0, marginLeft: 2 }}>✕</button>
          </div>
        )}

        <div className="new-ht">What do you want to build?</div>
        <div className="new-sub">Describe this run's goal in plain English. Be specific — include your target customer and key constraints.</div>

        <div className="f-field" style={{ marginBottom: 18 }}>
          <label className="f-label">Your goal</label>
          <textarea ref={goalRef} className="f-input f-ta" rows={5}
            placeholder="e.g. Build a go-to-market strategy for our enterprise segment, targeting CTOs at 50–500 person companies"
            onInput={(e) => setChars((e.target as HTMLTextAreaElement).value.length)} />
          <div className="f-hint">{chars} chars · aim for 50–400</div>
        </div>

        {/* Existing business context intake */}
        <div style={{ marginBottom: 18 }}>
          <button
            type="button"
            onClick={() => setShowExisting((v) => !v)}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              fontSize: 11, color: showExisting ? "var(--blue)" : "var(--fm)",
              background: showExisting ? "rgba(59,130,246,0.08)" : "transparent",
              border: `1px solid ${showExisting ? "var(--blue)" : "var(--bd)"}`,
              borderRadius: 20, padding: "4px 12px", cursor: "pointer",
            }}
          >
            <span style={{ fontSize: 13, lineHeight: 1 }}>{showExisting ? "▾" : "▸"}</span>
            {showExisting ? "Continuing an existing business" : "＋ I have an existing business"}
          </button>
          {showExisting && (
            <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10, padding: "16px", background: "var(--s2)", border: "1px solid var(--bd)", borderRadius: 8 }}>
              <div style={{ fontSize: 11, color: "var(--blue)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 2 }}>Existing business context</div>
              <div style={{ fontSize: 11, color: "var(--fm)", marginBottom: 4 }}>
                Add what exists so agents build on it, not from scratch. All fields optional.
              </div>

              <div className="f-field" style={{ marginBottom: 0 }}>
                <label className="f-label">GitHub repo URL</label>
                <input className="f-input" placeholder="https://github.com/org/repo"
                  value={exGithub} onChange={(e) => setExGithub(e.target.value)} />
                <div className="f-hint">Agents will build on this repo instead of creating a new one</div>
              </div>

              <div className="f-field" style={{ marginBottom: 0 }}>
                <label className="f-label">Live site / app URL</label>
                <input className="f-input" placeholder="https://yoursite.com"
                  value={exUrl} onChange={(e) => setExUrl(e.target.value)} />
                <div className="f-hint">Agents will visit and understand your current product</div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                <div className="f-field" style={{ marginBottom: 0 }}>
                  <label className="f-label">Monthly revenue</label>
                  <input className="f-input" placeholder="e.g. $2k MRR"
                    value={exRevenue} onChange={(e) => setExRevenue(e.target.value)} />
                </div>
                <div className="f-field" style={{ marginBottom: 0 }}>
                  <label className="f-label">Users / customers</label>
                  <input className="f-input" placeholder="e.g. 150 signups"
                    value={exUsers} onChange={(e) => setExUsers(e.target.value)} />
                </div>
                <div className="f-field" style={{ marginBottom: 0 }}>
                  <label className="f-label">Time in market</label>
                  <input className="f-input" placeholder="e.g. 6 months"
                    value={exAge} onChange={(e) => setExAge(e.target.value)} />
                </div>
              </div>

              <div className="f-field" style={{ marginBottom: 0 }}>
                <label className="f-label">Reference URLs <span style={{ color: "var(--fm)", fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>(competitors, inspiration, PRDs, docs)</span></label>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {exRefs.map((ref, i) => (
                    <div key={i} style={{ display: "flex", gap: 6 }}>
                      <input className="f-input" style={{ flex: 1 }}
                        placeholder={i === 0 ? "https://competitor.com or https://notion.so/my-prd" : "Another URL…"}
                        value={ref}
                        onChange={(e) => {
                          const next = [...exRefs];
                          next[i] = e.target.value;
                          setExRefs(next);
                        }}
                      />
                      {(exRefs.length > 1 || ref.trim() === "") && (
                        <button className="btn sm" type="button"
                          onClick={() => exRefs.length > 1 ? setExRefs(exRefs.filter((_, j) => j !== i)) : setExRefs([""])}>✕</button>
                      )}
                    </div>
                  ))}
                  {exRefs.length < 6 && (
                    <button className="btn sm" type="button" style={{ alignSelf: "flex-start" }}
                      onClick={() => setExRefs([...exRefs, ""])}>＋ Add URL</button>
                  )}
                </div>
                <div className="f-hint">Agents research competitors, read PRDs, and use these for context</div>
              </div>
            </div>
          )}
        </div>

        <div className="f-field" style={{ marginBottom: 18 }}>
          <label className="f-label">Stack</label>
          <div className="stack-grid">
            <div className={`sk auto${selStack === "" ? " sel" : ""}`} onClick={() => setSelStack("")}>
              <div className="sk-name">Auto-select</div>
              <div className="sk-desc">Astra picks the right agents for your goal automatically.</div>
              <div className="sk-ct">Recommended</div>
            </div>
            {stacks.map((s) => (
              <div key={s.stack_id} className={`sk${selStack === s.stack_id ? " sel" : ""}`} onClick={() => setSelStack(s.stack_id)}>
                <div className="sk-name">{s.name || s.stack_id}</div>
                <div className="sk-desc">{s.description || ""}</div>
                {Array.isArray(s.tasks) && s.tasks.length > 0 && <div className="sk-ct">{s.tasks.length} lanes</div>}
              </div>
            ))}
          </div>
          <div className="f-hint" style={{ marginTop: 7 }}>{stackHint}</div>
        </div>

        <div className="f-field" style={{ marginBottom: 18 }}>
          <label className="f-label">Run options <span style={{ color: "var(--fm)", fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>(optional)</span></label>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 160px" }}>
              <div className="f-hint" style={{ marginBottom: 4 }}>Technical scope</div>
              <select className="f-input" value={technicalScope} onChange={(e) => setTechnicalScope(e.target.value as TechnicalScope)}>
                <option value="both">Website + technical build</option>
                <option value="website">Website only</option>
                <option value="technical">Technical build only</option>
                <option value="none">Skip both</option>
              </select>
            </div>
            <div style={{ flex: "1 1 160px" }}>
              <div className="f-hint" style={{ marginBottom: 4 }}>Research depth</div>
              <select className="f-input" value={researchDepth} onChange={(e) => setResearchDepth(e.target.value as ResearchDepth | "")}>
                <option value="">Default (plan-based)</option>
                <option value="fast">Fast</option>
                <option value="deep">Deep</option>
              </select>
            </div>
            <div style={{ flex: "1 1 160px" }}>
              <div className="f-hint" style={{ marginBottom: 4 }}>Marketing channels</div>
              <select className="f-input" value={marketingChannels} onChange={(e) => setMarketingChannels(e.target.value as MarketingChannels)}>
                <option value="both">Organic + paid</option>
                <option value="organic">Organic only</option>
                <option value="paid">Paid included</option>
              </select>
            </div>
          </div>
        </div>

        <div className="f-field" style={{ marginBottom: 18 }}>
          <label className="f-label">Context files <span style={{ color: "var(--fm)", fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>(optional)</span></label>
          <label className="btn" style={{ display: "inline-flex", cursor: "pointer" }}>
            {uploading ? "Reading…" : "＋ Attach files"}
            <input type="file" multiple hidden onChange={(e) => onFiles(e.target.files)} />
          </label>
          {attachments.length > 0 && (
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
              {attachments.map((a, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, color: "var(--fd)", fontFamily: "var(--font-ibm-mono)" }}>
                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>📎 {a.name} ({a.content.length} chars)</span>
                  <button className="btn sm" onClick={() => setAttachments((p) => p.filter((_, j) => j !== i))}>✕</button>
                </div>
              ))}
            </div>
          )}
          <div className="f-hint">PDFs, docs, or images — Astra reads them as extra context for this run.</div>
        </div>

        {err && <div className="err-banner" style={{ marginBottom: 14 }}>{err}</div>}

        <div className="submit-row">
          <button className="btn pri" disabled={busy} onClick={submit}>{busy ? "Launching…" : "Launch Astra →"}</button>
          <button className="btn" onClick={() => router.push("/dashboard")}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
