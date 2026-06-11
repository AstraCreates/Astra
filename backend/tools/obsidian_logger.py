"""Obsidian vault tools — organized by founder / session / agent."""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)


def _sessions_root(founder_id: str | None = None) -> Path:
    base = Path(settings.obsidian_vault).expanduser()
    if founder_id:
        return base / "founders" / founder_id / "sessions"
    return base / "sessions"


def _session_dir(session_id: str, founder_id: str | None = None) -> Path:
    return _sessions_root(founder_id) / session_id


def _note_path(agent: str, session_id: str, founder_id: str | None = None) -> Path:
    return _session_dir(session_id, founder_id) / f"{agent}.md"


def _coerce_output(output: Any) -> dict | None:
    """Convert output to dict if it arrived as a JSON string from the LLM tool call."""
    if output is None:
        return None
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {"raw": output}
    return {"value": str(output)}


def obsidian_read(agent: str = "", max_notes: int = 5, founder_id: str | None = None, session_id: str | None = None, **kwargs) -> dict:
    """
    Read accumulated company knowledge this agent can use as context.

    Source of truth is the COMPANY BRAIN (GraphRAG): query it first. Legacy per-agent
    vault notes are only a fallback for when the brain has nothing yet (very early in a
    founder's first run, before any records are ingested).
    """
    # ── Primary: company brain / GraphRAG ──
    if founder_id and not kwargs.get("vault_only"):
        try:
            from backend.tools.company_brain import company_brain_context
            query = str(kwargs.get("query") or agent or "company context").strip()
            brain = company_brain_context(founder_id, query, limit=max_notes)
            if brain and brain.strip():
                return {
                    "notes": [{"file": "company_brain/graphrag", "content": brain[:16000]}],
                    "count": 1,
                    "summary": "Company brain (GraphRAG) context.",
                    "source": "company_brain",
                }
        except Exception:
            pass

    # ── Fallback: legacy vault notes ──
    root = _sessions_root(founder_id)
    if not root.exists():
        return {"notes": [], "summary": "No prior notes found."}

    # Collect all <agent>.md files from session dirs, sorted newest first
    matches = sorted(root.glob(f"*/{agent}.md"), reverse=True)[:max_notes]

    # Cap each note so repeated obsidian_read calls can't blow the model context
    # window (agents were hitting 290k+ tokens by re-reading large notes).
    _PER_NOTE_CAP = 4000
    results = []
    for note in matches:
        try:
            text = note.read_text()
            if len(text) > _PER_NOTE_CAP:
                text = text[:_PER_NOTE_CAP] + f"\n…[truncated, {len(text)} chars total]"
            results.append({"file": f"{note.parent.name}/{note.name}", "content": text})
        except Exception:
            pass

    return {
        "notes": results,
        "count": len(results),
        "summary": f"{len(results)} prior session(s) found." if results else "No prior sessions.",
    }


def format_vault_context(agent: str, max_notes: int = 3, founder_id: str | None = None) -> str:
    """Return vault notes as markdown for injection into agent prompts. Reads the vault
    directly (vault_only) — the brain/GraphRAG context is injected separately by the
    orchestrator, so this path must not double-inject it."""
    ctx = obsidian_read(agent, max_notes=max_notes, founder_id=founder_id, vault_only=True)
    notes = ctx.get("notes", [])
    if not notes:
        return ""

    lines = [f"## Your Prior Session Notes ({len(notes)} most recent)\n"]
    for note in notes:
        lines.append(f"### {note['file']}")
        lines.append(note["content"].strip())
        lines.append("")
    return "\n".join(lines)


def obsidian_log(
    agent: str,
    session_id: str,
    summary: str = "",
    output: Any = None,
    tags: list[str] = None,
    links: list[str] = None,
    founder_id: str | None = None,
    content: str = "",  # alias for summary
    **kwargs,
) -> dict:
    """
    Write a structured session note at:
      vault/founders/<founder_id>/sessions/<session_id>/<agent>.md
    """
    if content and not summary:
        summary = content
    folder = _session_dir(session_id, founder_id)
    folder.mkdir(parents=True, exist_ok=True)

    date = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H:%M")
    filename = _note_path(agent, session_id, founder_id)

    output_dict = _coerce_output(output)
    tag_str = " ".join(f"#{t}" for t in (tags or [])) or ""
    link_str = "\n".join(f"- {lnk}" for lnk in (links or []))

    sections = [
        "---",
        f"date: {date}",
        f"session: {session_id}",
        f"agent: {agent}",
        f"founder_id: {founder_id or 'default'}",
        f"tags: [{', '.join(tags or [])}]",
        "---",
        "",
        f"# {agent.capitalize()} · {date} {time_str}",
        "",
    ]

    if tag_str:
        sections += [tag_str, ""]

    sections += ["## Summary", summary or "(no summary)", ""]

    if output_dict:
        sections += ["## Outputs"]
        for key, val in output_dict.items():
            if isinstance(val, (dict, list)):
                sections.append(f"**{key}:**")
                sections.append(f"```json\n{json.dumps(val, indent=2)}\n```")
            else:
                sections.append(f"**{key}:** {val}")
        sections.append("")

    if links:
        sections += ["## Related", link_str, ""]

    filename.write_text("\n".join(sections))

    # Mirror the note into the COMPANY BRAIN so agent outputs become GraphRAG knowledge
    # (run_graph_rag_sync ingests brain records). Without this the brain never sees what
    # agents produce, so brain-backed reads would miss agent-generated context. Best-effort
    # — a brain-write failure must never fail the vault log.
    try:
        if founder_id and (summary or output_dict):
            from backend.tools.company_brain import add_company_brain_record
            # Write to FOUNDER-ROOT scope — that's what the GraphRAG sync, the
            # knowledge-map UI, and ask_company_brain all read. Scoping to the
            # session's ws_<id> company stranded agent outputs in subdirs the map
            # never reads, leaving the brain map empty. (One company per founder.)
            body = summary or ""
            if output_dict:
                body += "\n\n" + json.dumps(output_dict, indent=2)[:6000]
            add_company_brain_record(
                founder_id,
                source=f"agent:{agent}",
                title=f"{agent} — {date} {time_str}",
                content=body[:8000],
                kind="agent_output",
                metadata={"session_id": session_id, "agent": agent},
            )
    except Exception:
        pass

    return {"logged": True, "path": str(filename), "note": filename.name}


def obsidian_append(
    agent: str,
    session_id: str,
    heading: str,
    content: str,
    founder_id: str | None = None,
) -> dict:
    """Append a new section to an existing session note mid-run."""
    folder = _session_dir(session_id, founder_id)
    folder.mkdir(parents=True, exist_ok=True)
    filename = _note_path(agent, session_id, founder_id)

    if not filename.exists():
        date = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H:%M")
        filename.write_text(
            f"---\ndate: {date}\nsession: {session_id}\nagent: {agent}\n"
            f"founder_id: {founder_id or 'default'}\n---\n\n"
            f"# {agent.capitalize()} · {date} {time_str}\n\n## Summary\n(auto-created)\n"
        )

    existing = filename.read_text()
    filename.write_text(existing + f"\n## {heading}\n{content}\n")
    return {"appended": True, "heading": heading}


def auto_log_if_missing(
    agent: str,
    session_id: str,
    result: dict,
    founder_id: str | None = None,
) -> bool:
    """Write a vault note only if the agent didn't call obsidian_log itself."""
    filename = _note_path(agent, session_id, founder_id)
    if filename.exists():
        return False

    summary = result.get("summary") or result.get("output_summary") or "Agent completed task."
    if not isinstance(summary, str):
        summary = "Agent completed task."

    output_keys = {
        k: v for k, v in result.items()
        if k not in ("mirror_verdict", "mirror_critique") and v
    }

    obsidian_log(
        agent=agent,
        session_id=session_id,
        summary=f"[Auto-logged] {summary}",
        output=output_keys or None,
        tags=["auto-logged"],
        founder_id=founder_id,
    )
    return True


def obsidian_session_index(
    session_id: str,
    goal: str,
    agents_completed: list[str],
    founder_id: str | None = None,
) -> dict:
    """Write session index.md linking all agent notes for this run."""
    folder = _session_dir(session_id, founder_id)
    folder.mkdir(parents=True, exist_ok=True)

    date = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H:%M")
    filename = folder / "index.md"

    agent_links = [f"- [[{agent}]]" for agent in agents_completed]

    cross_pairs = [
        ("research", "web", "Research findings fed into landing page"),
        ("research", "legal", "Market context informed legal structure"),
        ("research", "marketing", "Market data used for campaign targeting"),
        ("research", "ops", "Market analysis included in exec summary"),
        ("web", "technical", "Landing page repo linked to scaffold"),
    ]
    cross_links = [
        f"- [[{a}]] → [[{b}]]: {note}"
        for a, b, note in cross_pairs
        if a in agents_completed and b in agents_completed
    ]

    sections = [
        "---",
        f"date: {date}",
        f"session: {session_id}",
        f"type: session-index",
        f"founder_id: {founder_id or 'default'}",
        f"agents: [{', '.join(agents_completed)}]",
        "---",
        "",
        f"# Session {session_id[:8]} · {date} {time_str}",
        "",
        f"**Goal:** {goal}",
        f"**Founder:** {founder_id or 'default'}",
        f"**Full session ID:** `{session_id}`",
        "",
        "## Agents",
        *agent_links,
        "",
    ]

    if cross_links:
        sections += ["## Cross-Agent Links", *cross_links, ""]

    filename.write_text("\n".join(sections))
    return {"indexed": True, "path": str(filename), "note": filename.name}


def obsidian_backend_log(
    session_id: str,
    founder_id: str,
    goal: str,
    events: list[tuple[int, dict]],
    results: dict[str, Any],
) -> dict:
    """
    Write a merged backend run log with full event timeline, tool IO, and final outputs
    including provenance for each extracted artifact.
    """
    folder = _session_dir(session_id, founder_id)
    folder.mkdir(parents=True, exist_ok=True)
    filename = folder / "backend_log.md"

    date = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H:%M")

    def _truncate(v: Any, n: int = 1600) -> str:
        try:
            s = json.dumps(v, indent=2, default=str) if not isinstance(v, str) else v
        except Exception:
            s = str(v)
        return s if len(s) <= n else s[:n] + "\n... (truncated)"

    lines: list[str] = [
        "---",
        f"date: {date}",
        f"session: {session_id}",
        "type: backend-log",
        f"founder_id: {founder_id}",
        "---",
        "",
        f"# Backend Session Log · {date} {time_str}",
        "",
        f"**Goal:** {goal}",
        f"**Session:** `{session_id}`",
        f"**Total events:** {len(events)}",
        "",
    ]

    # Timeline
    lines += ["## Event Timeline", ""]
    for eid, ev in events:
        et = ev.get("type", "unknown")
        agent = ev.get("agent")
        tool = ev.get("tool")
        prefix = f"- `#{eid}` `{et}`"
        if agent:
            prefix += f" · agent=`{agent}`"
        if tool:
            prefix += f" · tool=`{tool}`"
        lines.append(prefix)
        if et == "agent_action":
            args = ev.get("args", {})
            lines.append("  - args:")
            lines.append("```json")
            lines.append(_truncate(args, 800))
            lines.append("```")
        if et == "agent_action_result":
            lines.append("  - result:")
            lines.append("```json")
            lines.append(_truncate(ev.get("result"), 1200))
            lines.append("```")
    lines.append("")

    # Final outputs + provenance
    lines += ["## Final Outputs (with provenance)", ""]
    for task_id, output in results.items():
        out = output if isinstance(output, dict) else {"value": output}
        agent = out.get("agent") or "unknown"
        lines += [f"### Task `{task_id}` · Agent `{agent}`", ""]
        lines += ["```json", _truncate(out, 3000), "```", ""]

        # Artifact provenance by scanning timeline for this agent
        lines += ["#### Provenance", ""]
        found_any = False
        for eid, ev in events:
            if ev.get("agent") != agent:
                continue
            et = ev.get("type")
            if et not in ("agent_action", "agent_action_result", "agent_done", "agent_error"):
                continue
            found_any = True
            tool = ev.get("tool", "")
            lines.append(f"- source_event_id: `{eid}` · type: `{et}` · tool: `{tool}`")
        if not found_any:
            lines.append("- No explicit provenance events found for this output.")
        lines.append("")

    filename.write_text("\n".join(lines))
    return {"logged": True, "path": str(filename), "note": filename.name}
