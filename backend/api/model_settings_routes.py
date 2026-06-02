"""AI Model Settings — per-founder, per-agent model override endpoints.

Endpoints:
  GET    /api/model-settings?founder_id=x          — list overrides + available models
  POST   /api/model-settings                        — set an override
  DELETE /api/model-settings/{agent_key}?founder_id — clear an override
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.model_settings.store import (
    clear_override,
    get_all_overrides,
    set_model_override,
)

logger = logging.getLogger(__name__)

model_settings_router = APIRouter()

AVAILABLE_MODELS: list[str] = [
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


@model_settings_router.get("/model-settings")
async def get_model_settings(founder_id: str = Query(..., description="Founder ID")):
    """Return all overrides for a founder plus the list of available models."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    overrides = get_all_overrides(founder_id)
    return {
        "founder_id": founder_id,
        "overrides": overrides,
        "available_models": AVAILABLE_MODELS,
        "agent_keys": ALL_AGENT_KEYS,
    }


@model_settings_router.post("/model-settings")
async def set_model_settings(body: SetOverrideRequest):
    """Set or update a model override for a single agent."""
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
    if not body.agent_key:
        raise HTTPException(status_code=400, detail="agent_key is required")
    if body.agent_key not in ALL_AGENT_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown agent_key: {body.agent_key}")
    if body.model not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model: {body.model}. Available: {AVAILABLE_MODELS}")

    set_model_override(body.founder_id, body.agent_key, body.model)

    # Invalidate the orchestrator singleton so the new model is picked up next run
    try:
        from backend.core.factory import reload_model_overrides
        reload_model_overrides()
    except Exception as exc:
        logger.warning("Could not reload orchestrator after model override: %s", exc)

    return {
        "ok": True,
        "founder_id": body.founder_id,
        "agent_key": body.agent_key,
        "model": body.model,
    }


@model_settings_router.delete("/model-settings/{agent_key}")
async def delete_model_setting(agent_key: str, founder_id: str = Query(..., description="Founder ID")):
    """Clear a model override for a single agent, reverting to the default."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id is required")
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
