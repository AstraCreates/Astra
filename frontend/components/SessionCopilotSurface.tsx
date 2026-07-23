"use client";

import { Check, CircleAlert, FileText, Image as ImageIcon, Play, RotateCcw, Sparkles, Wrench } from "lucide-react";
import AstraCopilotComposer, { type CopilotAgentOption } from "@/components/AstraCopilotComposer";
import type { SessionImages } from "@/lib/api";

export type SessionActivityItem = {
  id: string;
  ts: number;
  agent?: string;
  label: string;
  detail?: string;
  kind: "start" | "action" | "done" | "error" | "goal" | "artifact";
};

function imageSrc(value: string): string {
  if (value.startsWith("data:") || value.startsWith("http://") || value.startsWith("https://")) return value;
  return `data:image/png;base64,${value}`;
}

export default function SessionCopilotSurface({
  goal,
  status,
  agents,
  activity,
  images,
  copilot,
  copilotBusy,
  copilotProgress,
  input,
  onInput,
  onSubmit,
  founderId,
  onOpenWorkbench,
  onImageRequest,
}: {
  goal: string;
  status: string;
  agents: CopilotAgentOption[];
  activity: SessionActivityItem[];
  images: SessionImages;
  copilot: { role: string; content: string; actions?: { tool: string; label: string; detail?: string; tone?: string; session_id?: string }[] }[];
  copilotBusy: boolean;
  copilotProgress: { turnId: string; text: string; phase: string; step: number } | null;
  input: string;
  onInput: (value: string) => void;
  onSubmit: (value: string, mentionedAgents: string[]) => void | Promise<void>;
  founderId?: string;
  onOpenWorkbench: () => void;
  onImageRequest: (agent: "design" | "marketing", prompt: string) => void;
}) {
  const running = agents.filter((agent) => agent.status === "running");
  const imagesList = [
    ...Object.entries(images.logos || {}).map(([style, base64]) => ({ key: `logo-${style}`, base64, prompt: `${style} logo`, kind: "logo" })),
    ...(images.brand_images || []).map((image, index) => ({ key: `brand-${index}`, base64: image.base64, prompt: image.prompt || "Brand image", kind: "brand" })),
  ].slice(-8);

  return (
    <main className="session-copilot-home session-copilot-workspace">
      <aside className="copilot-context-rail" aria-label="Session context">
        <div className="copilot-rail-kicker">Current run</div>
        <div className="copilot-run-status"><span className={status === "running" || status === "loading" ? "live-dot" : "is-done"} />{status === "running" || status === "loading" ? "In progress" : status === "done" ? "Complete" : status}</div>
        <div className="copilot-rail-section"><span>Goal</span><p>{goal || "Setting up the workspace..."}</p></div>
        <div className="copilot-rail-section"><span>Working now</span><div className="copilot-rail-agents">{running.length ? running.slice(0, 5).map((agent) => <button key={agent.id} type="button" onClick={() => onInput(`@${agent.id} `)}>{agent.label}<small>{agent.status}</small></button>) : <p className="copilot-muted">No agents are running.</p>}</div></div>
        <button type="button" className="copilot-workbench-link" onClick={onOpenWorkbench}>Open full Workbench <span>↗</span></button>
      </aside>

      <section className="copilot-main-column">
        <div className="session-copilot-intro">
          <img src="/astra-copilot.png" alt="Astra" />
          <div><span>{status === "running" || status === "loading" ? "Astra is working" : "Astra copilot"}</span><h1>{goal || "Your Astra workspace"}</h1><p>Ask for a readout, redirect work, or mention the exact agent you want to hear from.</p></div>
          <button type="button" onClick={onOpenWorkbench}>Workbench</button>
        </div>

        <div className="copilot-activity-panel">
          <div className="copilot-panel-heading"><span>Live session</span><small>{activity.length ? `${activity.length} updates` : "Waiting for the first update"}</small></div>
          <div className="copilot-activity-feed">
            {activity.length === 0 ? <div className="copilot-empty-activity">Astra will show starts, decisions, research summaries, technical progress, and completed work here.</div> : activity.slice(-14).map((item) => {
              const Icon = item.kind === "done" ? Check : item.kind === "error" ? CircleAlert : item.kind === "start" || item.kind === "goal" ? Play : item.kind === "artifact" ? FileText : Wrench;
              return <article key={item.id} className={`copilot-activity-item is-${item.kind}`}><Icon size={14} /><div><strong>{item.label}</strong>{item.detail && <p>{item.detail}</p>}</div></article>;
            })}
          </div>
        </div>

        <div className={`session-copilot-thread${copilot.length === 0 ? " is-empty" : ""}`}>
          {copilot.length === 0 ? <div className="session-copilot-starters"><button onClick={() => onInput("What is the team working on right now?")}>What is happening?</button><button onClick={() => onInput("What needs my attention?")}>What needs my attention?</button><button onClick={() => onInput("Summarize the strongest findings and next steps.")}>Summarize this run</button></div> : copilot.map((message, index) => <div key={index} className={`session-chat-row ${message.role === "founder" ? "is-founder" : "is-astra"}`}>{message.role !== "founder" && <span className="session-chat-avatar">A</span>}<div className="session-chat-bubble">{message.content}{message.actions && message.actions.length > 0 && <div className="copilot-actions">{message.actions.map((action, i) => <div key={`${action.tool}-${i}`} className={`copilot-action-card is-${action.tone || "info"}`}><div className="copilot-action-label">{action.label}</div>{action.detail && <div className="copilot-action-detail">{action.detail}</div>}{action.tool === "submit_goal" && action.session_id && <a href={`/s/${action.session_id}`} className="copilot-action-link">Open new run →</a>}</div>)}</div>}</div></div>)}
          {copilotBusy && <div className="session-chat-row is-astra"><span className="session-chat-avatar"><Sparkles size={14} /></span><div className="copilot-turn-progress" role="status" aria-live="polite"><span className={`copilot-turn-orbit is-${copilotProgress?.phase || "thinking"}`} /><div><strong>Astra is working</strong><p>{copilotProgress?.text || "Starting this turn."}</p>{copilotProgress?.step ? <small>Step {copilotProgress.step}</small> : null}</div></div></div>}
        </div>
        <AstraCopilotComposer value={input} onChange={onInput} onSubmit={onSubmit} agents={agents} disabled={copilotBusy} founderId={founderId} placeholder="Ask Astra anything or @mention a specific agent" contextLabel={`${running.length} working · ${agents.filter((agent) => agent.status === "done").length} done`} />
      </section>

      <aside className="copilot-artifact-rail" aria-label="Recent visual outputs">
        <div className="copilot-rail-kicker"><ImageIcon size={13} /> Visual outputs</div>
        {imagesList.length === 0 ? <div className="copilot-muted">Design and marketing images will appear here as soon as an agent creates them.</div> : <div className="copilot-image-grid">{imagesList.map((image) => <figure key={image.key} className="copilot-image-card"><img src={imageSrc(image.base64)} alt={image.prompt} /><figcaption><span>{image.prompt}</span><div><button type="button" onClick={() => onImageRequest("design", `Recreate this ${image.kind} with a stronger visual direction. Original prompt: ${image.prompt}`)}><RotateCcw size={11} /> Recreate</button><button type="button" onClick={() => onImageRequest("marketing", `Revise this ${image.kind} for marketing use. Original prompt: ${image.prompt}`)}><ImageIcon size={11} /> Revise</button></div></figcaption></figure>)}</div>}
      </aside>
    </main>
  );
}
