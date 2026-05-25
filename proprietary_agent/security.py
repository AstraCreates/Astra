"""
Tool Security Layer — validates every tool call before execution.

Enforces:
  1. Agent tool allowlists — agents can only call their declared tools
  2. Input sanitization — strips prompt injection attempts
  3. Founder isolation — no cross-founder data access
  4. Rate limiting — per tool per founder per hour
  5. Destructive action logging
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Allowlists (hardcoded — not LLM-configurable)
# ------------------------------------------------------------------ #

AGENT_TOOL_ALLOWLIST: dict[str, set[str]] = {
    "research": {
        "web_search", "news_search", "patent_search",
        "obsidian_log", "obsidian_read", "done",
        # specialized
        "academic_search", "competitor_intel", "market_sizing_model",
        "trend_detector", "regulatory_scanner",
    },
    "legal": {
        "format_legal_document", "generate_pdf",
        "obsidian_log", "obsidian_read", "done",
        # specialized
        "entity_formation_lookup", "compliance_checker", "contract_clause_library",
        "jurisdiction_analyzer", "ip_clearance_check", "term_sheet_analyzer",
    },
    "web": {
        "generate_landing_page_html", "vercel_deploy", "vercel_deploy_from_github", "github_create_repo",
        "web_search", "obsidian_log", "obsidian_read", "obsidian_append", "done",
        "cloudflare_setup_vercel_domain", "cloudflare_generate_instructions",
        "posthog_generate_integration", "clarity_generate_integration",
        # specialized
        "seo_keyword_research", "competitor_page_analyzer", "domain_availability",
        "conversion_benchmarks", "a_b_variant_generator", "page_speed_optimizer",
    },
    "marketing": {
        "generate_reel_package", "generate_tiktok_package", "generate_meta_ad",
        "send_email_campaign", "obsidian_log", "obsidian_read", "done",
        # specialized
        "audience_persona_builder", "competitor_ad_spy", "content_calendar_builder",
        "influencer_finder", "email_sequence_builder", "growth_channel_ranker",
    },
    "technical": {
        "github_create_repo", "claude_code_scaffold", "vercel_deploy_from_github",
        "composio_linear_create_issue", "composio_notion_create_page",
        "obsidian_log", "obsidian_read", "obsidian_append", "done",
        # Supabase
        "supabase_create_project", "supabase_create_table", "supabase_enable_rls",
        "supabase_setup_auth", "supabase_create_storage_bucket", "supabase_generate_schema",
        # Clerk
        "clerk_generate_integration", "clerk_generate_webhook_handler",
        # Cloudflare
        "cloudflare_create_dns_record", "cloudflare_setup_vercel_domain",
        "cloudflare_setup_email_dns", "cloudflare_generate_instructions",
        # Analytics
        "posthog_generate_integration", "posthog_create_key_events_spec",
        "clarity_generate_integration", "clarity_setup_for_app",
        # specialized
        "stack_recommender", "security_scanner", "dependency_auditor",
        "architecture_diagram_gen", "api_spec_generator", "infra_cost_estimator",
    },
    "ops": {
        "generate_pdf", "send_email_campaign",
        "composio_linear_create_issue", "composio_notion_create_page",
        "composio_gmail_send", "composio_calendar_create_event",
        "resend_send_email", "resend_generate_integration", "resend_create_email_templates",
        "obsidian_log", "obsidian_read", "obsidian_append", "done",
        # specialized
        "runway_calculator", "kpi_dashboard_builder", "investor_matcher",
        "cap_table_modeler", "competitive_positioning_map", "board_deck_generator",
    },
    "sales": {
        "find_leads", "enrich_lead", "build_outreach_sequence",
        "create_warming_schedule", "generate_spf_dkim_instructions",
        "build_crm_contact", "track_outreach", "send_email_campaign",
        "obsidian_log", "obsidian_read", "obsidian_append", "done",
        # specialized
        "icp_builder", "pipeline_analyzer", "deal_scorer", "competitor_battlecard",
    },
    "design": {
        "generate_wireframe", "generate_color_palette", "generate_design_spec",
        "generate_logo_brief", "web_search",
        "obsidian_log", "obsidian_read", "obsidian_append", "done",
        # specialized
        "accessibility_checker", "design_system_exporter", "figma_component_gen",
    },
    # Internal agents
    "mirror": {"done"},
    "observer": {"web_search", "news_search", "obsidian_log", "done"},
    "planner": {"done"},
}

# Tools that write external state — always logged for audit
DESTRUCTIVE_TOOLS = {
    "vercel_deploy", "vercel_deploy_from_github", "github_create_repo", "send_email_campaign",
    "claude_code_scaffold", "composio_linear_create_issue",
    "composio_notion_create_page", "supabase_create_project",
    "track_outreach",  # writes CRM state
}

# Patterns that signal prompt injection attempts
_INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"disregard (your|all) (previous |prior )?(instructions|context|rules)",
    r"you are now",
    r"system prompt",
    r"<\|.*?\|>",       # token boundary injection
    r"\[INST\]",        # Llama instruction injection
    r"###\s*Human:",    # alternate role injection
    r"assistant:\s*",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# Sensitive fields to redact from tool outputs before they enter LLM context
_SENSITIVE_KEYS = {
    "password", "secret", "token", "api_key", "apikey", "private_key",
    "access_token", "refresh_token", "authorization", "auth_header",
    "credit_card", "ssn", "social_security",
}


@dataclass
class ValidationResult:
    allowed: bool
    blocked: bool
    flagged: bool
    reason: str
    sanitized_args: dict

    @classmethod
    def allow(cls, args: dict, reason: str = "") -> "ValidationResult":
        return cls(allowed=True, blocked=False, flagged=False, reason=reason, sanitized_args=args)

    @classmethod
    def flag(cls, args: dict, reason: str) -> "ValidationResult":
        return cls(allowed=True, blocked=False, flagged=True, reason=reason, sanitized_args=args)

    @classmethod
    def block(cls, reason: str) -> "ValidationResult":
        return cls(allowed=False, blocked=True, flagged=False, reason=reason, sanitized_args={})


class ToolSecurityLayer:
    def __init__(self):
        # rate_limits[founder_id][tool] = list of call timestamps
        self._rate_limits: dict[str, dict[str, list[float]]] = {}
        self._rate_limit_per_hour = 20  # default per tool per founder

    def validate_call(self, agent: str, tool: str, args: dict, founder_id: str) -> ValidationResult:
        # 1. Allowlist check
        allowed_tools = AGENT_TOOL_ALLOWLIST.get(agent, set())
        if tool not in allowed_tools:
            reason = f"Agent '{agent}' is not permitted to call tool '{tool}'"
            logger.warning("SECURITY BLOCK: %s", reason)
            return ValidationResult.block(reason)

        # 2. Input sanitization
        sanitized = self._sanitize_inputs(args)

        # 3. Founder isolation
        isolation_check = self._check_founder_isolation(sanitized, founder_id)
        if isolation_check:
            logger.warning("SECURITY BLOCK: %s", isolation_check)
            return ValidationResult.block(isolation_check)

        # 4. Rate limit
        rate_check = self._check_rate_limit(founder_id, tool)
        if rate_check:
            logger.warning("SECURITY BLOCK: %s", rate_check)
            return ValidationResult.block(rate_check)

        # 5. Destructive action flag
        if tool in DESTRUCTIVE_TOOLS:
            reason = f"Destructive tool '{tool}' — logging for audit"
            logger.info("SECURITY FLAG: %s (founder=%s)", reason, founder_id)
            return ValidationResult.flag(sanitized, reason)

        return ValidationResult.allow(sanitized)

    def sanitize_output(self, tool: str, result: dict) -> dict:
        """Strip secrets and PII from tool results before LLM context ingestion."""
        return self._redact_sensitive_fields(result)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _sanitize_inputs(self, args: dict) -> dict:
        sanitized = {}
        for k, v in args.items():
            if isinstance(v, str):
                if _INJECTION_RE.search(v):
                    logger.warning("Prompt injection attempt detected in arg '%s' — sanitized", k)
                    v = re.sub(_INJECTION_RE, "[REDACTED]", v)
                sanitized[k] = v
            elif isinstance(v, dict):
                sanitized[k] = self._sanitize_inputs(v)
            else:
                sanitized[k] = v
        return sanitized

    def _check_founder_isolation(self, args: dict, founder_id: str) -> str | None:
        if "founder_id" in args and args["founder_id"] != founder_id:
            return f"Cross-founder data access denied (caller={founder_id}, requested={args['founder_id']})"
        return None

    def _check_rate_limit(self, founder_id: str, tool: str) -> str | None:
        now = time.monotonic()
        window = 3600  # 1 hour
        self._rate_limits.setdefault(founder_id, {}).setdefault(tool, [])
        calls = self._rate_limits[founder_id][tool]
        # Evict old timestamps
        calls[:] = [t for t in calls if now - t < window]
        if len(calls) >= self._rate_limit_per_hour:
            return f"Rate limit exceeded: {tool} called {len(calls)} times in the last hour (limit={self._rate_limit_per_hour})"
        calls.append(now)
        return None

    def _redact_sensitive_fields(self, data: Any, depth: int = 0) -> Any:
        if depth > 5:
            return data
        if isinstance(data, dict):
            return {
                k: "[REDACTED]" if k.lower() in _SENSITIVE_KEYS else self._redact_sensitive_fields(v, depth + 1)
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [self._redact_sensitive_fields(item, depth + 1) for item in data]
        return data


# Singleton used by engine
_security_layer = ToolSecurityLayer()


def get_security_layer() -> ToolSecurityLayer:
    return _security_layer
