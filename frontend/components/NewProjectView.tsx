"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getStacks, createWorkspace, ingestAttachment, type AgentStackTemplate } from "@/lib/api";
import { useDevUser } from "@/lib/use-dev-user";

const STAGES = ["Idea / Pre-product", "Building MVP", "Early Customers", "Growing Revenue", "Scaling"];
const INDUSTRIES = [
  "SaaS / Software", "Marketplace", "E-commerce", "Fintech", "Healthtech",
  "Edtech", "AI / ML", "Creator Economy", "B2B Services", "Hardware", "Other",
];

export default function NewProjectView() {
  const router = useRouter();
  const { userId } = useDevUser();
  const [stacks, setStacks] = useState<AgentStackTemplate[]>([]);
  const [selStack, setSelStack] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [uploading, setUploading] = useState(false);
  const [attachments, setAttachments] = useState<{ name: string; content: string }[]>([]);

  // Form fields
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [description, setDescription] = useState("");
  const [customer, setCustomer] = useState("");
  const [stage, setStage] = useState(STAGES[0]);
  const [industry, setIndustry] = useState(INDUSTRIES[0]);

  useEffect(() => {
    getStacks().then((s) => setStacks(s)).catch(() => {});
  }, []);

  const onFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    for (const f of Array.from(files)) {
      try {
        const r = await ingestAttachment(userId, f, true);
        if (r.content) setAttachments((p) => [...p, { name: r.filename || f.name, content: r.content }]);
        else if (r.error) setErr(`⚠ ${f.name}: ${r.error}`);
      } catch (e) { setErr(`⚠ ${f.name}: ${e instanceof Error ? e.message : String(e)}`); }
    }
    setUploading(false);
  };

  const submit = async () => {
    if (!name.trim()) { setErr("⚠ Company name is required."); return; }
    if (!description.trim()) { setErr("⚠ Please describe what your company does."); return; }
    setBusy(true);
    setErr("");
    try {
      // Build a rich goal string that captures all the company context
      const goal = [
        `Company: ${name.trim()}`,
        domain ? `Website: ${domain.trim()}` : null,
        `Industry: ${industry}`,
        `Stage: ${stage}`,
        `Description: ${description.trim()}`,
        customer ? `Target customer: ${customer.trim()}` : null,
        attachments.length ? `\nAttached context:\n${attachments.map((a) => `--- ${a.name} ---\n${a.content.slice(0, 6000)}`).join("\n\n")}` : null,
      ].filter(Boolean).join("\n");

      const ws = await createWorkspace(userId, name.trim(), goal, selStack || "idea_to_revenue");
      // Navigate to workspace view — no run started yet, user kicks off runs from there
      router.push(`/?workspace=${ws.workspace_id}&founder=${encodeURIComponent(userId)}`);
    } catch (e) {
      setBusy(false);
      setErr(`⚠ ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div style={{ flex: 1, overflowY: "auto" }}>
      <div className="new-wrap" style={{ maxWidth: 640 }}>
        <div className="new-ht">Set up your project</div>
        <div className="new-sub">Tell Astra about your company. You can start runs from the project dashboard once it's set up.</div>

        {/* Company name */}
        <div className="f-field">
          <label className="f-label">Company name <span style={{ color: "var(--red)" }}>*</span></label>
          <input className="f-input" type="text" placeholder="e.g. InvoiceFlow" maxLength={80}
            value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        {/* Domain */}
        <div className="f-field">
          <label className="f-label">Website / domain <span style={{ color: "var(--fm)", fontWeight: 400, textTransform: "none" }}>(optional)</span></label>
          <input className="f-input" type="text" placeholder="e.g. invoiceflow.com"
            value={domain} onChange={(e) => setDomain(e.target.value)} />
        </div>

        {/* Industry + Stage row */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div className="f-field">
            <label className="f-label">Industry</label>
            <select className="f-input" value={industry} onChange={(e) => setIndustry(e.target.value)}
              style={{ appearance: "none", cursor: "pointer" }}>
              {INDUSTRIES.map((i) => <option key={i}>{i}</option>)}
            </select>
          </div>
          <div className="f-field">
            <label className="f-label">Stage</label>
            <select className="f-input" value={stage} onChange={(e) => setStage(e.target.value)}
              style={{ appearance: "none", cursor: "pointer" }}>
              {STAGES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
        </div>

        {/* Description */}
        <div className="f-field">
          <label className="f-label">What does your company do? <span style={{ color: "var(--red)" }}>*</span></label>
          <textarea className="f-input f-ta" rows={4}
            placeholder="e.g. We help freelancers track invoices and get paid faster through automated payment reminders and one-click invoicing."
            value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>

        {/* Target customer */}
        <div className="f-field">
          <label className="f-label">Who is your target customer? <span style={{ color: "var(--fm)", fontWeight: 400, textTransform: "none" }}>(optional)</span></label>
          <input className="f-input" type="text" placeholder="e.g. Freelance designers and developers with 5–50 clients"
            value={customer} onChange={(e) => setCustomer(e.target.value)} />
        </div>

        {/* Stack */}
        <div className="f-field">
          <label className="f-label">Astra stack</label>
          <div className="stack-grid">
            <div className={`sk auto${selStack === "" ? " sel" : ""}`} onClick={() => setSelStack("")}>
              <div className="sk-name">Auto-select</div>
              <div className="sk-desc">Astra picks the right agents for your goal.</div>
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
        </div>

        {/* Context files */}
        <div className="f-field">
          <label className="f-label">Context files <span style={{ color: "var(--fm)", fontWeight: 400, textTransform: "none" }}>(optional)</span></label>
          <label className="btn" style={{ display: "inline-flex", cursor: "pointer" }}>
            {uploading ? "Reading…" : "＋ Attach files"}
            <input type="file" multiple hidden onChange={(e) => onFiles(e.target.files)} />
          </label>
          <div className="f-hint">Pitch deck, market research, competitor analysis — Astra reads them as context for every run.</div>
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
          <button className="btn pri" disabled={busy || !name.trim() || !description.trim()} onClick={submit}>
            {busy ? "Creating project…" : "Create project →"}
          </button>
          <button className="btn" onClick={() => router.push("/")}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
