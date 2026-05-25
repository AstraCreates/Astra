"""Obsidian vault tools for agents — read past context, write structured session notes."""
import json
from datetime import datetime
from pathlib import Path

from backend.config import settings


def _vault() -> Path:
    return Path(settings.obsidian_vault)


def obsidian_read(agent: str, max_notes: int = 5) -> dict:
    """
    Read recent session notes from the agent's vault folder.
    Returns accumulated knowledge the agent can use as context.
    """
    folder = _vault() / agent
    if not folder.exists():
        return {"notes": [], "summary": "No prior notes found."}

    notes = sorted(folder.glob("*.md"), reverse=True)
    # Skip README
    notes = [n for n in notes if n.stem != "README"][:max_notes]

    results = []
    for note in notes:
        try:
            text = note.read_text()
            results.append({"file": note.name, "content": text[:2000]})
        except Exception:
            pass

    return {
        "notes": results,
        "count": len(results),
        "summary": f"{len(results)} prior session(s) found." if results else "No prior sessions.",
    }


def obsidian_log(
    agent: str,
    session_id: str,
    summary: str,
    output: dict = None,
    tags: list[str] = None,
    links: list[str] = None,
) -> dict:
    """
    Write a structured session note to the agent's vault folder.
    - summary: what the agent did this session (prose)
    - output: key results as a dict (files created, URLs, decisions)
    - tags: obsidian tags e.g. ["nda", "acmeco"]
    - links: wikilinks to other agent notes e.g. ["[[research/2026-05-24-abc]]"]
    """
    folder = _vault() / agent
    folder.mkdir(parents=True, exist_ok=True)

    date = datetime.now().strftime("%Y-%m-%d")
    time = datetime.now().strftime("%H:%M")
    filename = folder / f"{date}-{session_id[:8]}.md"

    tag_str = " ".join(f"#{t}" for t in (tags or [])) or ""
    link_str = "\n".join(f"- {l}" for l in (links or []))

    sections = [
        f"---",
        f"date: {date}",
        f"session: {session_id}",
        f"agent: {agent}",
        f"tags: [{', '.join(tags or [])}]",
        f"---",
        f"",
        f"# {agent.capitalize()} · {date} {time}",
        f"",
    ]

    if tag_str:
        sections += [tag_str, ""]

    sections += ["## Summary", summary, ""]

    if output:
        sections += ["## Outputs"]
        for key, val in output.items():
            if isinstance(val, (dict, list)):
                sections.append(f"**{key}:**")
                sections.append(f"```json\n{json.dumps(val, indent=2)[:1500]}\n```")
            else:
                sections.append(f"**{key}:** {val}")
        sections.append("")

    if links:
        sections += ["## Related", link_str, ""]

    filename.write_text("\n".join(sections))
    return {"logged": True, "path": str(filename), "note": filename.name}


def obsidian_append(agent: str, session_id: str, heading: str, content: str) -> dict:
    """Append a new section to an existing session note mid-run."""
    folder = _vault() / agent
    date = datetime.now().strftime("%Y-%m-%d")
    filename = folder / f"{date}-{session_id[:8]}.md"

    if not filename.exists():
        # Auto-create a minimal note so append doesn't silently fail
        folder.mkdir(parents=True, exist_ok=True)
        date = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H:%M")
        filename.write_text(
            f"---\ndate: {date}\nsession: {session_id}\nagent: {agent}\n---\n\n"
            f"# {agent.capitalize()} · {date} {time_str}\n\n## Summary\n(auto-created)\n"
        )

    existing = filename.read_text()
    addition = f"\n## {heading}\n{content}\n"
    filename.write_text(existing + addition)
    return {"appended": True, "heading": heading}
