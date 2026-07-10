"""AI Model Settings — per-founder, per-agent model override endpoints.

Endpoints:
  GET    /api/model-settings?founder_id=x          — list overrides + available models
  POST   /api/model-settings                        — set an override
  DELETE /api/model-settings/{agent_key}?founder_id — clear an override
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.model_settings.store import (
    clear_override,
    get_all_overrides,
    set_model_override,
)
from backend.tenant_auth import FounderActor, current_founder_from_query, require_current_founder

logger = logging.getLogger(__name__)

model_settings_router = APIRouter()

AVAILABLE_MODELS: list[str] = [
    "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-v4-flash",
    "inclusionai/ling-2.6-flash",
    "openai/gpt-oss-120b",
    "tencent/hy3-preview",
    "xiaomi/mimo-v2.5",
    "xiaomi/mimo-v2.5-pro",
    "google/gemma-3-27b-it",
    "deepseek-ai/DeepSeek-V4-Flash",
    "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
    "Qwen/Qwen3-32B",
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
    "zai-org/GLM-4.7-Flash",
]

ALL_AGENT_KEYS: list[str] = [
    "research",
    "research_competitors",
    "research_execution",
    "research_market",
    "research_financial",
    "research_regulatory",
    "web",
    "marketing",
    "marketing_content",
    "marketing_outreach",
    "marketing_seo",
    "marketing_paid",
    "technical",
    "technical_scaffold",
    "technical_infra",
    "technical_data",
    "legal",
    "legal_docs",
    "legal_entity",
    "legal_ip",
    "sales",
    "sales_pipeline",
    "sales_enablement",
    "ops",
    "design",
    "finance_model",
    "finance_fundraise",
]


class SetOverrideRequest(BaseModel):
    founder_id: str
    agent_key: str
    model: str


def require_model_settings_admin_actor(body: SetOverrideRequest, request: Request) -> FounderActor:
    return require_current_founder(request, body.founder_id, min_role="admin")


@model_settings_router.get("/model-settings")
async def get_model_settings(actor: FounderActor = Depends(current_founder_from_query(min_role="viewer"))):
    """Return all overrides for a founder plus the list of available models."""
    founder_id = actor.founder_id
    overrides = get_all_overrides(founder_id)
    return {
        "founder_id": founder_id,
        "overrides": overrides,
        "available_models": AVAILABLE_MODELS,
        "agent_keys": ALL_AGENT_KEYS,
    }


@model_settings_router.post("/model-settings")
async def set_model_settings(
    body: SetOverrideRequest,
    actor: FounderActor = Depends(require_model_settings_admin_actor),
):
    """Set or update a model override for a single agent."""
    founder_id = actor.founder_id
    if not body.agent_key:
        raise HTTPException(status_code=400, detail="agent_key is required")
    if body.agent_key not in ALL_AGENT_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown agent_key: {body.agent_key}")
    if body.model not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model: {body.model}. Available: {AVAILABLE_MODELS}")

    set_model_override(founder_id, body.agent_key, body.model)

    # Invalidate the orchestrator singleton so the new model is picked up next run
    try:
        from backend.core.factory import reload_model_overrides
        reload_model_overrides()
    except Exception as exc:
        logger.warning("Could not reload orchestrator after model override: %s", exc)

    return {
        "ok": True,
        "founder_id": founder_id,
        "agent_key": body.agent_key,
        "model": body.model,
    }


@model_settings_router.delete("/model-settings/{agent_key}")
async def delete_model_setting(
    agent_key: str,
    actor: FounderActor = Depends(current_founder_from_query(min_role="admin")),
):
    """Clear a model override for a single agent, reverting to the default."""
    founder_id = actor.founder_id
    if agent_key not in ALL_AGENT_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown agent_key: {agent_key}")

    existed = clear_override(founder_id, agent_key)

    # Invalidate the orchestrator singleton
    try:
        from backend.core.factory import reload_model_overrides
        reload_model_overrides()
    except Exception as exc:
        logger.warning("Could not reload orchestrator after model override clear: %s", exc)

    return {
        "ok": True,
        "founder_id": founder_id,
        "agent_key": agent_key,
        "was_set": existed,
    }
