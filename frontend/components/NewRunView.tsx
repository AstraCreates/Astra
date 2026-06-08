"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getStacks, getWorkspace, submitGoal, ingestAttachment, type AgentStackTemplate, type Workspace } from "@/lib/api";
import { useDevUser } from "@/lib/use-dev-user";

export default function NewRunView({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const { userId } = useDevUser();
  const goalRef = useRef<HTMLTextAreaElement>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [stacks, setStacks] = useState<AgentStackTemplate[]>([]);
  const [selStack, setSelStack] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [uploading, setUploading] = useState(false);
  const [attachments, setAttachments] = useState<{ name: string; content: string }[]>([]);
  const [chars, setChars] = useState(0);

  useEffect(() => {
    getWorkspace(workspaceId).then(setWorkspace).catch(() => {});
    getStacks().then(setStacks).catch(() => {});
  }, [workspaceId]);

  const onFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    for (const f of Array.from(files)) {
      try {
        const r = await ingestAttachment(userId, f, true);
        if (r.content) setAttachments((p) => [...p, { name: r.filename || f.name, content: r.content }]);
        else if (r.error) setErr(`⚠ ${f.name}: ${r.error}`);
      } catch (e) { setErr(`⚠ ${e instanceof Error ? e.message : String(e)}`); }
    }
    setUploading(false);
  };

  const submit = async () => {
    const goal = goalRef.current?.value.trim() || "";
    if (goal.length < 10) { setErr("⚠ Please describe your goal in more detail."); return; }
    setBusy(true);
    setErr("");
    try {
      // Build instruction: company context from workspace + this run's goal
      const companyCtx = workspace?.goal || "";
      let instruction = companyCtx ? `${companyCtx}\n\n---\nRun goal: ${goal}` : goal;
      if (attachments.length) {
        instruction += "\n\nAdditional context for this run:\n" + attachments.map((a) => `--- ${a.name} ---\n${a.content.slice(0, 6000)}`).join("\n\n");
      }
      const data = await submitGoal(userId, instruction, {}, selStack || workspace?.stack_id || "idea_to_revenue", workspaceId);
      if (!data.session_id) throw new Error("No session_id returned");
      // Open the live session (AppHome is session-based). Hard nav so it always lands.
      window.location.assign(`/s/${data.session_id}`);
    } catch (e) {
      setBusy(false);
      setErr(`⚠ ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div style={{ flex: 1, overflowY: "auto" }}>
      <div className="new-wrap" style={{ maxWidth: 580 }}>
        {/* Company context chip */}
        {workspace && (
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "6px 12px", borderRadius: 20, border: "1px solid var(--bd)", background: "var(--surface)", marginBottom: 20, fontSize: 11, color: "var(--fd)" }}>
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--blue)", flexShrink: 0 }} />
            <span style={{ fontWeight: 600, color: "var(--fg)" }}>{workspace.company_name || workspace.name}</span>
            <span style={{ color: "var(--fm)" }}>· New run</span>
          </div>
        )}

        <div className="new-ht">What do you want to build?</div>
        <div className="new-sub">Describe the goal for this run. Astra already knows your company context.</div>

        <div className="f-field">
          <label className="f-label">Run goal</label>
          <textarea ref={goalRef} className="f-input f-ta" rows={5}
            placeholder="e.g. Build out our go-to-market strategy for the enterprise segment"
            onInput={(e) => setChars((e.target as HTMLTextAreaElement).value.length)} />
          <div className="f-hint">{chars} chars</div>
        </div>

        {/* Stack — show only if different from workspace default */}
        <div className="f-field">
          <label className="f-label">Stack <span style={{ color: "var(--fm)", fontWeight: 400, textTransform: "none" }}>(optional override)</span></label>
          <div className="stack-grid">
            <div className={`sk auto${selStack === "" ? " sel" : ""}`} onClick={() => setSelStack("")}>
              <div className="sk-name">Use project default</div>
              <div className="sk-desc">{workspace?.stack_id || "Auto-selected for your project"}</div>
            </div>
            {stacks.map((s) => (
              <div key={s.stack_id} className={`sk${selStack === s.stack_id ? " sel" : ""}`} onClick={() => setSelStack(s.stack_id)}>
                <div className="sk-name">{s.name || s.stack_id}</div>
                <div className="sk-desc">{s.description || ""}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Extra context files */}
        <div className="f-field">
          <label className="f-label">Additional context <span style={{ color: "var(--fm)", fontWeight: 400, textTransform: "none" }}>(optional)</span></label>
          <label className="btn" style={{ display: "inline-flex", cursor: "pointer" }}>
            {uploading ? "Reading…" : "＋ Attach files"}
            <input type="file" multiple hidden onChange={(e) => onFiles(e.target.files)} />
          </label>
          <div className="f-hint">Extra docs relevant to this specific run — adds to the project-level context Astra already has.</div>
          {attachments.length > 0 && (
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
              {attachments.map((a, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, color: "var(--fd)", fontFamily: "var(--font-ibm-mono)" }}>
                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>📎 {a.name}</span>
                  <button className="btn sm" onClick={() => setAttachments((p) => p.filter((_, j) => j !== i))}>✕</button>
                </div>
              ))}
            </div>
          )}
        </div>

        {err && <div className="err-banner">{err}</div>}

        <div className="submit-row">
          <button className="btn pri" disabled={busy} onClick={submit}>
            {busy ? "Launching…" : "Launch run →"}
          </button>
          <button className="btn" onClick={() => router.push(`/?workspace=${workspaceId}&founder=${encodeURIComponent(userId)}`)}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
