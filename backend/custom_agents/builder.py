"""Turn a custom agent spec (data) into a live Agent and inject it into the
orchestrator alongside the built-in specialists.

The orchestrator resolves every task by `self.specialists[agent_id]`, so a custom
agent just needs to be present in that dict under its namespaced id. Ids are
founder-namespaced (`custom_<founder>_<slug>`) so leaving them registered is safe
across founders and concurrent runs.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.config import settings
from backend.core.agent import Agent
from backend.custom_agents.tool_catalog import (
    CONNECTOR_BY_KEY,
    connectors_for_tool_keys,
    resolve_tools,
)

logger = logging.getLogger(__name__)


# Model alias → resolver. Keeps custom agents on the same models the platform
# already pays for, instead of letting founders pin arbitrary expensive models.
_MODEL_ALIASES = {
    "small": lambda: settings.or_light_model,
    "light": lambda: settings.or_light_model,
    "highoutput": lambda: settings.or_highoutput_model,
    "planner": lambda: settings.or_planner_model,
}


def _model_kwargs(model: str) -> dict[str, Any]:
    """Resolve a spec's model field to Agent model kwargs (always via OpenRouter)."""
    from backend.core.key_rotator import get_openrouter_key

    or_key = get_openrouter_key() or settings.agent_model_api_key
    or_base = settings.openrouter_base_url
    resolver = _MODEL_ALIASES.get((model or "").lower())
    model_id = resolver() if resolver else (model or settings.or_highoutput_model)
    return {
        "model": model_id,
        "model_base_url": or_base,
        "model_api_key": or_key,
    }


def _augment_role(spec: dict[str, Any]) -> str:
    """Wrap the founder's prompt with the minimum operating contract every Astra
    agent needs: persist results, finish with `done`. The founder's text stays the
    dominant instruction."""
    role = (spec.get("role") or "").strip()
    return (
        f"{role}\n\n"
        "OPERATING RULES:\n"
        "- Use only the tools listed above. If a needed tool isn't available, do the "
        "best you can with what you have and note the gap in your output.\n"
        "- When finished, call obsidian_log to save your work, then call done with a "
        "structured output object summarizing what you produced."
    )


def build_custom_agent(spec: dict[str, Any]) -> tuple[Agent, list[str]]:
    """Build an Agent from a spec. Returns (agent, unresolved_tool_keys)."""
    tools, unresolved = resolve_tools(list(spec.get("tool_keys") or []))
    agent = Agent(
        name=spec["id"],
        role=_augment_role(spec),
        tools=tools,
        use_computer=bool(spec.get("use_computer")),
        **_model_kwargs(spec.get("model", "highoutput")),
    )
    if unresolved:
        logger.warning("custom_agent %s: unresolved tools %s", spec["id"], unresolved)
    return agent, unresolved


def register_custom_agents(founder_id: str, agent_ids: list[str] | None = None) -> list[str]:
    """Build + inject a founder's custom agents into the orchestrator.

    If agent_ids is given, only those are registered; otherwise all of the
    founder's custom agents are. Returns the list of agent ids registered.
    """
    from backend.core.factory import get_orchestrator
    from backend.custom_agents import store

    orch = get_orchestrator()
    specs = store.list_agents(founder_id)
    if agent_ids:
        wanted = set(agent_ids)
        specs = [s for s in specs if s["id"] in wanted]

    registered: list[str] = []
    for spec in specs:
        try:
            agent, _ = build_custom_agent(spec)
            orch.specialists[spec["id"]] = agent
            registered.append(spec["id"])
        except Exception as exc:
            logger.error("custom_agent %s build/register failed: %s", spec.get("id"), exc, exc_info=True)
    if registered:
        logger.info("Registered %d custom agent(s) for founder=%s: %s", len(registered), founder_id, registered)
    return registered


# ── Connector readiness ───────────────────────────────────────────────────────

def connector_readiness(founder_id: str, tool_keys: list[str], company_id: str | None = None) -> dict[str, Any]:
    """Which connectors this tool set needs, and which are missing for the founder.

    Returns {required: [...], missing: [...], ready: bool}. Used by the UI to ask
    the founder to connect things before the agent runs.
    """
    required = connectors_for_tool_keys(tool_keys)
    if not required:
        return {"required": [], "missing": [], "ready": True}

    # Composio app connection status (one lookup, reused for every composio connector).
    composio_status: dict[str, bool] = {}
    if any(CONNECTOR_BY_KEY.get(k) and CONNECTOR_BY_KEY[k].kind == "composio" for k in required):
        try:
            from backend.tools.integration_connect import get_composio_app_status
            composio_status = get_composio_app_status(founder_id) or {}
        except Exception as exc:
            logger.warning("composio app status lookup failed: %s", exc)

    # A key connector is ready when its credentials are present + shape-valid.
    _READY = {"validated", "locally_valid"}
    missing: list[str] = []
    for key in required:
        meta = CONNECTOR_BY_KEY.get(key)
        # Gmail: check direct OAuth credentials first (bypasses broken Composio)
        if key == "gmail":
            try:
                from backend.provisioning.credentials_store import load_credentials
                gmail_creds = load_credentials(founder_id, "gmail") or {}
                if gmail_creds.get("access_token") or gmail_creds.get("refresh_token"):
                    continue  # connected via direct OAuth
            except Exception:
                pass
            missing.append(key)
            continue
        if meta and meta.kind == "composio":
            slug = meta.composio_slug or key
            if not composio_status.get(slug):
                missing.append(key)
            continue
        # key-based connector
        try:
            from backend.connector_validation import validate_connector
            result = validate_connector(founder_id, key)
            if result.get("status") not in _READY:
                missing.append(key)
        except Exception as exc:
            logger.warning("connector validate failed for %s: %s", key, exc)
            missing.append(key)

    return {"required": required, "missing": missing, "ready": not missing}
