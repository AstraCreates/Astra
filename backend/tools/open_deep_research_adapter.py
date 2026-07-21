"""Astra adapter for the LangChain Open Deep Research supervisor graph.

The upstream graph owns planning, delegation, reflection, and final synthesis.
This adapter supplies the researcher workers with Astra's Company OS MCP
boundary instead of letting the graph silently use a separate search backend.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from threading import Lock
from typing import Any


async def run_open_deep_research(subject: str, *, company_id: str, initiative_id: str | None = None,
                                 squad_id: str | None = None, mission_id: str | None = None,
                                 task_id: str | None = None) -> dict[str, Any]:
    from langchain_core.tools import tool
    from open_deep_research import deep_researcher as graph_module
    from open_deep_research.state import ResearchComplete
    from open_deep_research.utils import think_tool
    from backend.config import settings
    from backend.tools._llm import _or_api_key

    calls: list[dict[str, Any]] = []

    @tool("astra_company_research", description="Run one bounded, cited research pass through Astra Company OS MCP.")
    async def astra_company_research(research_topic: str) -> str:
        from backend.company_os_mcp import invoke
        result = await asyncio.to_thread(
            invoke, company_id, "astra_company_research",
            {"subject": research_topic, "focus": "market", "deep_worker": True},
            task_id=task_id, mission_id=mission_id, squad_id=squad_id,
            initiative_id=initiative_id,
        )
        calls.append({"topic": research_topic, "status": "validated" if result.get("ok") else "incomplete",
                      "search_count": (result.get("evidence_validation") or {}).get("search_count", 0),
                      "source_count": (result.get("evidence_validation") or {}).get("source_count", 0),
                      "model": (result.get("research_metadata") or {}).get("model"),
                      "sources": result.get("sources") or []})
        return json.dumps(result, default=str)

    async def astra_tools(_config: Any):
        # Preserve the upstream supervisor's think/research-complete tools;
        # only replace the worker's external research surface.
        return [tool(ResearchComplete), think_tool, astra_company_research]

    # Headroom is the right transport for Astra's normal model lanes, but its
    # LiteLLM provider map does not understand the upstream graph's
    # ``openai:deepseek/...`` provider notation. Keep this profile isolated and
    # use the OpenRouter-compatible endpoint directly.
    configured_base = str(settings.openrouter_base_url or "")
    research_base = ("https://openrouter.ai/api/v1"
                     if "headroom" in configured_base.lower()
                     else configured_base)
    profile_env = {
        "OPENAI_API_KEY": _or_api_key(),
        "OPENAI_BASE_URL": research_base,
        # Configuration.from_runnable_config gives environment variables
        # precedence over LangGraph's configurable values. Pin every model
        # field for this profile so a stale production lane cannot silently
        # replace DeepSeek or re-enable a non-Astra search provider.
        "RESEARCH_MODEL": "openai:deepseek/deepseek-v4-flash",
        "COMPRESSION_MODEL": "openai:deepseek/deepseek-v4-flash",
        "FINAL_REPORT_MODEL": "openai:deepseek/deepseek-v4-flash",
        "SUMMARIZATION_MODEL": "openai:deepseek/deepseek-v4-flash",
        "SEARCH_API": "none",
        "ALLOW_CLARIFICATION": "false",
    }
    previous_env = {name: os.environ.get(name) for name in profile_env}
    os.environ.update(profile_env)
    await asyncio.to_thread(_GRAPH_PATCH_LOCK.acquire)
    try:
        original_get_all_tools = graph_module.get_all_tools
        graph_module.get_all_tools = astra_tools
        try:
            result = await asyncio.wait_for(
                graph_module.deep_researcher.ainvoke(
                    {"messages": [{"role": "user", "content": subject}]},
                    {"configurable": {
                        "research_model": "openai:deepseek/deepseek-v4-flash",
                        "compression_model": "openai:deepseek/deepseek-v4-flash",
                        "final_report_model": "openai:deepseek/deepseek-v4-flash",
                        "allow_clarification": False,
                        "search_api": "none",
                        "max_researcher_iterations": 6,
                        "max_concurrent_research_units": 3,
                        "max_react_tool_calls": 8,
                    }},
                ),
                timeout=float(settings.deep_research_timeout_seconds),
            )
        finally:
            graph_module.get_all_tools = original_get_all_tools
    finally:
        _GRAPH_PATCH_LOCK.release()
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    report = str(result.get("final_report") or "").strip()
    sources = [dict(source) for call in calls for source in call.get("sources", []) if isinstance(source, dict)]
    retrieval_time = datetime.now(timezone.utc).isoformat()
    for source in sources:
        source.setdefault("retrieved_at", retrieval_time)
    delegated = bool(calls)
    source_count = sum(int(item.get("source_count") or 0) for item in calls)
    search_count = sum(int(item.get("search_count") or 0) for item in calls)
    return {"report": report, "combined_formatted": report, "sources": sources,
            "structured": {"delegated_research": calls}, "research_calls": calls,
            "deep_research_supervisor": True, "delegated": delegated,
            "search_count": search_count, "source_count": source_count,
            "queries_run": search_count, "coverage": {"ready": bool(delegated and source_count > 0), "gaps": []},
            "research_status": "validated" if delegated and report and source_count > 0 else "evidence_incomplete",
            "research_metadata": {"profile": "open_deep_research_langgraph",
                                  "model": "deepseek/deepseek-v4-flash",
                                  "provider": "deepseek",
                                  "transport": "direct_openrouter" if "headroom" in configured_base.lower() else research_base}}
_GRAPH_PATCH_LOCK = Lock()
