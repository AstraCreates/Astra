"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getStacks, submitGoal, ingestAttachment, type AgentStackTemplate } from "@/lib/api";
import { useDevUser } from "@/lib/use-dev-user";

export default function NewGoalView() {
  const router = useRouter();
  const { userId } = useDevUser();
  const [stacks, setStacks] = useState<AgentStackTemplate[]>([]);
  const [stackHint, setStackHint] = useState("Loading stacks…");
  const [selStack, setSelStack] = useState<string>("");
  const [chars, setChars] = useState(0);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachments, setAttachments] = useState<{ name: string; content: string }[]>([]);
  const [uploading, setUploading] = useState(false);
  const [company, setCompany] = useState("");
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

  const submit = async () => {
    const goal = goalRef.current?.value.trim() || "";
    setErr("");
    if (goal.length < 10) { setErr("⚠ Please describe your goal in more detail (min 10 chars)."); return; }
    setBusy(true);
    try {
      // Prepend the founder's chosen company name so the backend uses it (NOT a
      // generated one). Must be "Company/project name:" — the prefix the name
      // extractor recognizes (plain "Company:" was ignored → random names).
      let instruction = displayCompany ? `Company/project name: ${displayCompany}\n\n${goal}` : goal;
      if (attachments.length) {
        instruction += "\n\nAttached context:\n" + attachments.map((a) => `--- ${a.name} ---\n${a.content.slice(0, 8000)}`).join("\n\n");
      }
      const data = await submitGoal(
        userId,
        instruction,
        {},
        selStack || "idea_to_revenue",
      );
      if (!data.session_id) throw new Error("No session_id returned");
      window.location.assign(`/s/${data.session_id}`);
    } catch (e) {
      setBusy(false);
      setErr(`⚠ ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div style={{ flex: 1, overflowY: "auto" }}>
      <div className="new-wrap">
        {displayCompany && (
          <div style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "4px 10px", borderRadius: 20, border: "1px solid var(--bd)", background: "var(--surface)", fontSize: 10.5, color: "var(--fd)", marginBottom: 16 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--blue)" }} />
            <span style={{ fontWeight: 600, color: "var(--fg)" }}>{displayCompany}</span>
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
          <button className="btn" onClick={() => router.push("/")}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
