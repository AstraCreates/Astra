"""
Builds the live Orchestrator with all specialists and the planner agent.
Called once at startup; cached as a module-level singleton.
"""
from backend.core.agent import Agent
from backend.core.orchestrator import Orchestrator
from backend.config import settings
from backend.specialists.research import build_research_agent
from backend.specialists.web import build_web_agent
from backend.specialists.brand_marketing import build_brand_marketing_agent
from backend.specialists.technical import build_technical_agent
from backend.specialists.legal_compliance import build_legal_compliance_agent
from backend.specialists.revenue_ops import build_revenue_ops_agent
from backend.specialists.lead_generation import build_lead_generation_agent
from backend.specialists.design import build_design_agent
from backend.specialists.customer_discovery import build_customer_discovery_agent
from backend.specialists.product_strategy import build_product_strategy_agent
from backend.specialists.research_financial import build_research_financial_agent
from backend.specialists.research_regulatory import build_research_regulatory_agent
from backend.specialists.legal_contracts import build_legal_contracts_agent
from backend.specialists.legal_entity import build_legal_entity_agent
from backend.specialists.legal_ip import build_legal_ip_agent
from backend.specialists.content_engine import build_content_engine_agent
from backend.specialists.growth_hacking import build_growth_hacking_agent
from backend.specialists.marketing_seo import build_marketing_seo_agent
from backend.specialists.marketing_paid import build_marketing_paid_agent
from backend.specialists.sales_pipeline import build_sales_pipeline_agent
from backend.specialists.sales_enablement import build_sales_enablement_agent
from backend.specialists.technical_api import build_technical_api_agent
from backend.specialists.technical_infra import build_technical_infra_agent
from backend.specialists.technical_data import build_technical_data_agent
from backend.specialists.finance_model import build_finance_model_agent
from backend.specialists.finance_fundraise import build_finance_fundraise_agent
from backend.specialists.web_automator import build_web_automator_agent

_orchestrator: Orchestrator | None = None


def reload_model_overrides() -> None:
    """Invalidate the orchestrator singleton so it is rebuilt with new model settings on next call."""
    global _orchestrator
    _orchestrator = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        # Use OR-prefixed fields — Coolify doesn't override these (new names)
        # get_openrouter_key() rotates across all configured keys round-robin
        from backend.core.key_rotator import get_openrouter_key
        _or_key = get_openrouter_key() or settings.agent_model_api_key
        _or_base = settings.openrouter_base_url  # always https://openrouter.ai/api/v1
        _coder_kwargs = dict(
            model=settings.or_planner_model,    # hy3-preview
            model_base_url=_or_base,
            model_api_key=_or_key,
        )
        _deepseek_kwargs = dict(
            model="deepseek-ai/DeepSeek-V4-Flash",
            model_base_url=settings.agent_model_base_url,
            model_api_key=settings.agent_model_api_key,
        )
        _highoutput_kwargs = dict(
            model=settings.or_highoutput_model,  # hy3-preview via OpenRouter
            model_base_url=_or_base,
            model_api_key=_or_key,
        )
        _small_kwargs = dict(
            model=settings.or_light_model,  # ling-2.6-flash
            model_base_url=_or_base,
            model_api_key=_or_key,
        )
        _large_ctx_kwargs = _deepseek_kwargs
        specialists = {
            # Research cluster — each owns a distinct intelligence domain
            "research": build_research_agent(agent_name="research", use_computer=True),
            "research_competitors": build_research_agent(agent_name="research_competitors", use_computer=True),
            "customer_discovery": build_customer_discovery_agent(use_computer=True),
            "research_financial": build_research_financial_agent(use_computer=True, **_large_ctx_kwargs),
            "research_regulatory": build_research_regulatory_agent(use_computer=True, **_large_ctx_kwargs),
            # Strategy
            "product_strategy": build_product_strategy_agent(use_computer=True, **_coder_kwargs),
            # Web & Technical cluster — each owns a distinct build layer
            "web": build_web_agent(use_computer=True, **_coder_kwargs),
            "technical": build_technical_agent(use_computer=True, **_highoutput_kwargs),
            "technical_api": build_technical_api_agent(use_computer=True, **_highoutput_kwargs),
            "technical_infra": build_technical_infra_agent(use_computer=True, **_highoutput_kwargs),
            "technical_data": build_technical_data_agent(use_computer=True, **_highoutput_kwargs),
            # Design
            "design": build_design_agent(use_computer=False, **_highoutput_kwargs),
            # Legal cluster — formation, contracts, IP, compliance (no overlap)
            "legal_entity": build_legal_entity_agent(use_computer=True, **_highoutput_kwargs),
            "legal_contracts": build_legal_contracts_agent(use_computer=True, **_highoutput_kwargs),
            "legal_ip": build_legal_ip_agent(use_computer=True, **_highoutput_kwargs),
            "legal_compliance": build_legal_compliance_agent(use_computer=True, **_highoutput_kwargs),
            # Marketing cluster — positioning, content, SEO, paid, growth (no overlap)
            "brand_marketing": build_brand_marketing_agent(use_computer=True, **_highoutput_kwargs),
            "content_engine": build_content_engine_agent(use_computer=True, **_highoutput_kwargs),
            "marketing_seo": build_marketing_seo_agent(use_computer=True, max_tool_calls={"search_and_fetch": 3, "web_search": 5}, **_highoutput_kwargs),
            "marketing_paid": build_marketing_paid_agent(use_computer=True, max_tool_calls={"search_and_fetch": 4, "web_search": 6}, **_highoutput_kwargs),
            "growth_hacking": build_growth_hacking_agent(use_computer=True, **_highoutput_kwargs),
            # Sales cluster — sourcing, pipeline, enablement (no overlap)
            "lead_generation": build_lead_generation_agent(use_computer=False, **_small_kwargs),
            "sales_pipeline": build_sales_pipeline_agent(use_computer=False, **_small_kwargs),
            "sales_enablement": build_sales_enablement_agent(use_computer=False, **_highoutput_kwargs),
            # Finance & Revenue cluster
            "finance_model": build_finance_model_agent(use_computer=True, **_highoutput_kwargs),
            "finance_fundraise": build_finance_fundraise_agent(use_computer=True, **_highoutput_kwargs),
            "revenue_ops": build_revenue_ops_agent(use_computer=True, **_coder_kwargs),
            # Web automation — autonomous browser agent for any web task
            "web_automator": build_web_automator_agent(use_computer=True, **_coder_kwargs),
        }
        from backend.tools.company_brain import (
            add_company_brain_record,
            ask_company_brain,
            company_brain_agent_context,
            configure_company_brain_sync,
            get_company_brain_sync_status,
            ingest_company_brain_records,
            maintain_company_brain,
            run_due_company_brain_syncs,
            run_company_brain_sync,
            search_company_brain,
            sync_company_brain,
        )
        from backend.tools.company_brain_connectors import (
            import_company_brain_source,
            import_company_brain_sources,
        )
        for agent in specialists.values():
            agent.tools.setdefault("company_brain_search", search_company_brain)
            agent.tools.setdefault("company_brain_sync", sync_company_brain)
            agent.tools.setdefault("company_brain_add_record", add_company_brain_record)
            agent.tools.setdefault("company_brain_ingest_records", ingest_company_brain_records)
            agent.tools.setdefault("company_brain_maintain", maintain_company_brain)
            agent.tools.setdefault("company_brain_agent_context", company_brain_agent_context)
            agent.tools.setdefault("company_brain_ask", ask_company_brain)
            agent.tools.setdefault("company_brain_configure_sync", configure_company_brain_sync)
            agent.tools.setdefault("company_brain_sync_status", get_company_brain_sync_status)
            agent.tools.setdefault("company_brain_run_sync", run_company_brain_sync)
            agent.tools.setdefault("company_brain_run_due_syncs", run_due_company_brain_syncs)
            agent.tools.setdefault("company_brain_import_source", import_company_brain_source)
            agent.tools.setdefault("company_brain_import_sources", import_company_brain_sources)
        planner = Agent(
            name="planner",
            role=(
                "You are the planning coordinator. Decompose founder goals into specialist tasks. "
                "Each specialist owns a DISTINCT, non-overlapping domain — never assign the same work to two agents.\n\n"
                "AGENT ROSTER:\n"
                "Research: research (market opportunity/TAM), research_competitors (named competitors/pricing), "
                "customer_discovery (ICP/JTBD/personas), research_financial (unit economics benchmarks), "
                "research_regulatory (regulatory risk map)\n"
                "Strategy: product_strategy (MVP scope, RICE prioritization, north star metric)\n"
                "Build: web (marketing landing page + shared repo), technical (product MVP/auth/dashboard), "
                "technical_api (API design/OpenAPI spec), technical_infra (DevOps/CI-CD/hosting), "
                "technical_data (Postgres schema/analytics events)\n"
                "Design: design (logo/colors/typography/wireframes)\n"
                "Legal: legal_entity (company formation/cap table), legal_contracts (MSA/DPA/NDAs), "
                "legal_ip (patents/trademarks/trade secrets), legal_compliance (GDPR/SOC2/privacy-by-design)\n"
                "Marketing: brand_marketing (positioning/messaging/ad creatives), content_engine (social scripts/email/blog), "
                "marketing_seo (keyword strategy/content SEO), marketing_paid (Google+Meta campaigns), "
                "growth_hacking (viral loops/referral programs/PLG hooks)\n"
                "Sales: lead_generation (prospect sourcing/ICP scoring/enrichment), "
                "sales_pipeline (CRM stages/deal qualification), sales_enablement (pitch deck/battlecards)\n"
                "Finance: finance_model (12-month P&L/unit economics), finance_fundraise (investor research/SAFE/one-pager), "
                "revenue_ops (Stripe setup/pricing/billing/churn recovery), "
                "web_automator (autonomous browser — sign in/up, API key extraction, form fill, purchases on ANY website)"
            ),
            tools={},
            sub_agents=list(specialists.values()),
            model=settings.or_planner_model,
            model_base_url=_or_base,
            model_api_key=_or_key,
        )
        _orchestrator = Orchestrator(planner=planner, specialists=specialists)
    return _orchestrator
