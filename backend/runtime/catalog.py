"""Production tool metadata and specialist manifest migration helpers."""
from __future__ import annotations

import inspect
from typing import Any, Callable

from backend.runtime.manifests import DelegationPolicy, SpecialistManifest
from backend.runtime.tool_guardrails import MUTATING_TOOLS, READ_ONLY_TOOLS
from backend.runtime.tool_registry import ToolEntry, registry, schema_from_callable

TOOLSET_BY_PREFIX = {
    "company_brain": "company_brain_read",
    "obsidian": "company_brain_write",
    "web_search": "research",
    "news_search": "research",
    "search": "research",
    "fetch": "research",
    "batch_search": "research",
    "patent": "research",
    "youtube": "research",
    "tiktok_research": "research",
    "generate_pdf": "documents",
    "format_legal": "documents",
    "generate_design": "design",
    "generate_wireframe": "design",
    "generate_logo": "design",
    "generate_brand": "design",
    "github": "code",
    "run_mvp": "code",
    "run_claude": "code",
    "write_files": "code",
    "spawn_parallel": "code",
    "vercel": "deployment",
    "cloudflare": "deployment",
    "build_outreach": "outreach_prepare",
    "find_leads": "outreach_prepare",
    "hunter": "crm",
    "apollo": "crm",
    "send_email": "outreach_send",
    "composio_gmail": "outreach_send",
    "composio_linkedin": "outreach_send",
    "composio_linear": "project_management",
    "composio_notion": "project_management",
    "create_stripe": "billing",
    "create_product_with_payment": "billing",
    "supabase_create": "provisioning",
    "vision_browse": "provisioning",
    "run_web_task": "provisioning",
    "file_llc": "provisioning",
}

EXTERNAL_PREFIXES = (
    "send_", "composio_gmail", "composio_linkedin", "vercel_", "cloudflare_",
    "create_stripe", "create_product_with_payment", "file_llc", "supabase_create",
)
ONE_SHOT_PREFIXES = (
    "vercel_", "github_create_repo", "generate_landing_page_html",
    "claude_code_scaffold", "file_llc",
)


def infer_toolset(name: str) -> str:
    for prefix, toolset in TOOLSET_BY_PREFIX.items():
        if name.startswith(prefix):
            return toolset
    return "general"


def infer_context_fields(handler: Callable) -> frozenset[str]:
    try:
        params = inspect.signature(handler).parameters
    except Exception:
        return frozenset()
    return frozenset(name for name in ("session_id", "founder_id", "agent") if name in params)


def infer_mutability(name: str) -> str:
    if name in MUTATING_TOOLS or name.startswith(EXTERNAL_PREFIXES):
        return "external"
    if name in READ_ONLY_TOOLS or infer_toolset(name) in {"research", "company_brain_read"}:
        return "read"
    return "write"


def register_agent_tools(agent: Any) -> dict[str, ToolEntry]:
    entries: dict[str, ToolEntry] = {}
    for name, handler in agent.tools.items():
        existing = registry.get(name)
        if existing is not None:
            # Specialist wrappers are intentionally local, so preserve them in
            # the agent while retaining shared metadata from the first entry.
            entries[name] = ToolEntry(
                **{**existing.__dict__, "handler": handler, "is_async": inspect.iscoroutinefunction(handler)}
            )
            continue
        mutability = infer_mutability(name)
        toolset = infer_toolset(name)
        entry = ToolEntry(
            name=name,
            toolset=toolset,
            schema=schema_from_callable(name, handler),
            handler=handler,
            is_async=inspect.iscoroutinefunction(handler),
            description=(inspect.getdoc(handler) or "").splitlines()[0] if inspect.getdoc(handler) else name,
            risk_category=toolset if mutability == "external" else None,
            mutability=mutability,
            context_fields=infer_context_fields(handler),
            one_shot=name.startswith(ONE_SHOT_PREFIXES),
        )
        registry.register(entry)
        entries[name] = entry
    return entries


def manifest_for_agent(agent: Any) -> SpecialistManifest:
    entries = register_agent_tools(agent)
    return SpecialistManifest(
        name=agent.name,
        role=agent.role,
        model_policy=agent.model,
        toolsets=tuple(sorted({entry.toolset for entry in entries.values()})),
        max_iterations=agent._max_iterations or 20,
        max_cost_usd=getattr(agent, "_max_cost_usd", None),
        delegation_policy=DelegationPolicy(
            allowed_roles=tuple(sorted(agent.sub_agents)),
        ),
        one_shot_tools=frozenset(name for name, entry in entries.items() if entry.one_shot),
        max_tool_calls=dict(agent._max_tool_calls),
    )


def migrate_agent(agent: Any) -> Any:
    entries = register_agent_tools(agent)
    agent._runtime_entries = entries
    agent.toolsets = sorted({entry.toolset for entry in entries.values()})
    agent.manifest = manifest_for_agent(agent)
    return agent


def validate_catalog(agents: dict[str, Any]) -> None:
    available_tools = set(registry.snapshot())
    available_toolsets = set(registry.toolsets())
    errors: list[str] = []
    for name, agent in agents.items():
        manifest = agent.manifest or manifest_for_agent(agent)
        agent.manifest = manifest
        for error in manifest.validate(available_tools, available_toolsets):
            errors.append(f"{name}: {error}")
        for tool_name, entry in agent._runtime_entries.items():
            if entry.mutability == "external" and not entry.risk_category:
                errors.append(f"{name}: external tool {tool_name} lacks approval metadata")
    if errors:
        raise RuntimeError("Invalid specialist catalog:\n" + "\n".join(errors))
