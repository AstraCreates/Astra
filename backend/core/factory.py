"""
Builds the live Orchestrator with all specialists and the planner agent.
Called once at startup; cached as a module-level singleton.
"""
from backend.core.agent import Agent
from backend.core.orchestrator import Orchestrator
from backend.config import settings
from backend.specialists.research import build_research_agent
from backend.specialists.web import build_web_agent
from backend.specialists.marketing import build_marketing_agent
from backend.specialists.technical import build_technical_agent
from backend.specialists.legal import build_legal_agent
from backend.specialists.ops import build_ops_agent
from backend.specialists.sales import build_sales_agent
from backend.specialists.design import build_design_agent
from backend.specialists.research_market import build_research_market_agent
from backend.specialists.research_financial import build_research_financial_agent
from backend.specialists.research_regulatory import build_research_regulatory_agent
from backend.specialists.legal_docs import build_legal_docs_agent
from backend.specialists.legal_entity import build_legal_entity_agent
from backend.specialists.legal_ip import build_legal_ip_agent
from backend.specialists.marketing_content import build_marketing_content_agent
from backend.specialists.marketing_outreach import build_marketing_outreach_agent
from backend.specialists.marketing_seo import build_marketing_seo_agent
from backend.specialists.marketing_paid import build_marketing_paid_agent
from backend.specialists.sales_pipeline import build_sales_pipeline_agent
from backend.specialists.sales_enablement import build_sales_enablement_agent
from backend.specialists.technical_scaffold import build_technical_scaffold_agent
from backend.specialists.technical_infra import build_technical_infra_agent
from backend.specialists.technical_data import build_technical_data_agent
from backend.specialists.finance_model import build_finance_model_agent
from backend.specialists.finance_fundraise import build_finance_fundraise_agent
from backend.specialists.web_navigator import build_web_navigator_agent

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
            model=settings.or_light_model,  # xiaomi/mimo-v2.5
            model_base_url=_or_base,
            model_api_key=_or_key,
        )
        _technical_kwargs = dict(
            model=settings.technical_agent_model or settings.or_light_model,
            model_base_url=_or_base,
            model_api_key=_or_key,
            max_iterations=settings.technical_agent_max_iterations,
            max_tool_calls={"run_mvp_loop": 1, "spawn_parallel_coders": 1, "github_create_repo": 1,
                            "obsidian_read": 1, "obsidian_log": 2, "vision_browse": 6},
        )
        specialists = {
            # Research — MiMo for fast, repeated, source-grounded cycles
            "research": build_research_agent(agent_name="research", use_computer=True, **_small_kwargs),
            "research_competitors": build_research_agent(agent_name="research_competitors", use_computer=True, **_small_kwargs),
            "research_execution": build_research_agent(agent_name="research_execution", use_computer=True, **_small_kwargs),
            "research_customers": build_research_agent(agent_name="research_customers", use_computer=True, **_small_kwargs),
            "research_gtm": build_research_agent(agent_name="research_gtm", use_computer=True, **_small_kwargs),
            "research_market": build_research_market_agent(use_computer=True, **_small_kwargs),
            "research_financial": build_research_financial_agent(use_computer=True, **_small_kwargs),
            "research_regulatory": build_research_regulatory_agent(use_computer=True, **_small_kwargs),
            # Web — hy3-preview (best tool calling for deploy/HTML gen)
            "web": build_web_agent(use_computer=True, **{**_coder_kwargs, "model": settings.web_agent_model}),
            # Technical wrapper — cheap router/logger; run_mvp_loop owns the heavy coding model.
            "technical": build_technical_agent(use_computer=False, **_technical_kwargs),
            "technical_scaffold": build_technical_scaffold_agent(use_computer=True, **_highoutput_kwargs),
            "technical_infra": build_technical_infra_agent(use_computer=True, **_highoutput_kwargs),
            "technical_data": build_technical_data_agent(use_computer=True, **_highoutput_kwargs),
            # Marketing — mimo-v2.5. On hy3-preview it never finished its task (mangled
            # tool-call JSON / no agent_done), which left goal tasks perpetually open and
            # spawned endless follow-up runs. mimo completes its tool workflow reliably.
            "marketing": build_marketing_agent(use_computer=True, **_small_kwargs),
            "legal": build_legal_agent(use_computer=True, **_highoutput_kwargs),
            "ops": build_ops_agent(use_computer=True, **_coder_kwargs),
            # Design — mimo-v2.5 (fast, clean tool calls). It works through tools
            # (brand board, wireframe, logo brief), so it doesn't need a heavy reasoning
            # model; hy3-preview here ran 20+ min per stuck iteration ("design took ages").
            "design": build_design_agent(use_computer=False, **_small_kwargs),
            "legal_docs": build_legal_docs_agent(use_computer=True, **_highoutput_kwargs),
            "legal_entity": build_legal_entity_agent(use_computer=True, **_highoutput_kwargs),
            "legal_ip": build_legal_ip_agent(use_computer=True, **_highoutput_kwargs),
            "marketing_content": build_marketing_content_agent(use_computer=True, **_highoutput_kwargs),
            "marketing_outreach": build_marketing_outreach_agent(use_computer=True, **_small_kwargs),
            "marketing_seo": build_marketing_seo_agent(use_computer=True, max_tool_calls={"search_and_fetch": 3, "web_search": 5}, **_highoutput_kwargs),
            "marketing_paid": build_marketing_paid_agent(use_computer=True, max_tool_calls={"search_and_fetch": 4, "web_search": 6}, **_highoutput_kwargs),
            "sales_enablement": build_sales_enablement_agent(use_computer=False, **_highoutput_kwargs),
            "finance_model": build_finance_model_agent(use_computer=True, **_highoutput_kwargs),
            "finance_fundraise": build_finance_fundraise_agent(use_computer=True, **_highoutput_kwargs),
            # Short repeated-output task agents — MiMo (fast, cheap)
            "sales": build_sales_agent(use_computer=False, max_iterations=15, **_small_kwargs),
            "sales_pipeline": build_sales_pipeline_agent(use_computer=False, **_small_kwargs),
            # Web Navigator — vision-driven autonomous browser agent
            # Uses Gemini Flash vision via OpenRouter for screenshot → action loop
            "web_navigator": build_web_navigator_agent(use_computer=True, **_highoutput_kwargs),
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
        # Dashboard tools — available to every agent so any specialist can add tiles
        from backend.tools.dashboard_tools import (
            dashboard_add_element,
            dashboard_remove_element,
            dashboard_clear,
            dashboard_get,
        )
        from backend.tools.ask_user_tool import ask_user
        # Only agents that legitimately need founder clarification before acting get ask_user.
        # Specialist agents (design, marketing, legal, sales, finance, research*) work from
        # their brief — injecting ask_user causes 300s blocks when nobody is watching.
        # web_navigator excluded: it drives the browser autonomously; asking questions mid-crawl
        # would stall the session just like research agents did.
        _ask_user_agents = {"ops", "technical", "technical_scaffold", "technical_infra", "technical_data", "web"}
        for name, agent in specialists.items():
            agent.tools.setdefault("dashboard_add_element", dashboard_add_element)
            agent.tools.setdefault("dashboard_remove_element", dashboard_remove_element)
            agent.tools.setdefault("dashboard_clear", dashboard_clear)
            agent.tools.setdefault("dashboard_get", dashboard_get)
            if name in _ask_user_agents:
                agent.tools.setdefault("ask_user", ask_user)

        # Integration tools — ops, marketing, and content agents for ecomm/local_service stacks
        from backend.tools.klaviyo_tools import (
            klaviyo_create_list, klaviyo_add_to_list,
            klaviyo_create_campaign, klaviyo_get_metrics,
        )
        from backend.tools.printful_tools import (
            printful_get_products, printful_create_store_product,
            printful_get_orders, printful_create_order,
        )
        from backend.tools.lemonsqueezy_tools import (
            ls_create_product, ls_get_sales, ls_create_discount,
        )
        from backend.tools.square_tools import (
            square_list_services, square_create_service,
            square_create_booking, square_list_bookings, square_get_revenue,
        )
        from backend.tools.twilio_tools import (
            twilio_send_sms, twilio_send_bulk_sms,
            twilio_create_messaging_service, twilio_get_usage,
        )
        from backend.tools.yelp_tools import (
            yelp_search_businesses, yelp_get_business,
            yelp_get_reviews, yelp_search_categories,
        )
        _integration_agent_names = {
            "ops", "marketing", "marketing_content", "marketing_outreach",
            "marketing_seo", "marketing_paid", "sales", "sales_pipeline",
            "sales_enablement", "research", "research_competitors",
            "research_customers", "research_gtm",
        }
        for name, agent in specialists.items():
            if name not in _integration_agent_names:
                continue
            # Klaviyo / email marketing
            agent.tools.setdefault("klaviyo_create_list", klaviyo_create_list)
            agent.tools.setdefault("klaviyo_add_to_list", klaviyo_add_to_list)
            agent.tools.setdefault("klaviyo_create_campaign", klaviyo_create_campaign)
            agent.tools.setdefault("klaviyo_get_metrics", klaviyo_get_metrics)
            # Printful / POD
            agent.tools.setdefault("printful_get_products", printful_get_products)
            agent.tools.setdefault("printful_create_store_product", printful_create_store_product)
            agent.tools.setdefault("printful_get_orders", printful_get_orders)
            agent.tools.setdefault("printful_create_order", printful_create_order)
            # Lemon Squeezy / digital sales
            agent.tools.setdefault("ls_create_product", ls_create_product)
            agent.tools.setdefault("ls_get_sales", ls_get_sales)
            agent.tools.setdefault("ls_create_discount", ls_create_discount)
            # Square / POS + bookings
            agent.tools.setdefault("square_list_services", square_list_services)
            agent.tools.setdefault("square_create_service", square_create_service)
            agent.tools.setdefault("square_create_booking", square_create_booking)
            agent.tools.setdefault("square_list_bookings", square_list_bookings)
            agent.tools.setdefault("square_get_revenue", square_get_revenue)
            # Twilio / SMS
            agent.tools.setdefault("twilio_send_sms", twilio_send_sms)
            agent.tools.setdefault("twilio_send_bulk_sms", twilio_send_bulk_sms)
            agent.tools.setdefault("twilio_create_messaging_service", twilio_create_messaging_service)
            agent.tools.setdefault("twilio_get_usage", twilio_get_usage)
            # Yelp / local business research
            agent.tools.setdefault("yelp_search_businesses", yelp_search_businesses)
            agent.tools.setdefault("yelp_get_business", yelp_get_business)
            agent.tools.setdefault("yelp_get_reviews", yelp_get_reviews)
            agent.tools.setdefault("yelp_search_categories", yelp_search_categories)

        # Examples library — inject into every agent so all specialists can search patterns
        from backend.tools.examples_library import search_examples, list_example_categories
        for agent in specialists.values():
            agent.tools.setdefault("search_examples", search_examples)
            agent.tools.setdefault("list_example_categories", list_example_categories)

        from backend.runtime.catalog import migrate_agent, validate_catalog
        for agent in specialists.values():
            migrate_agent(agent)
        validate_catalog(specialists)
        planner = Agent(
            name="planner",
            role="planning coordinator. Decompose founder goals into specialist tasks scoped to each agent's actual capabilities.",
            tools={
                "dashboard_add_element": dashboard_add_element,
                "dashboard_remove_element": dashboard_remove_element,
                "dashboard_clear": dashboard_clear,
                "dashboard_get": dashboard_get,
                "ask_user": ask_user,
            },
            sub_agents=list(specialists.values()),
            model=settings.or_planner_model,
            model_base_url=_or_base,
            model_api_key=_or_key,
        )
        _orchestrator = Orchestrator(planner=planner, specialists=specialists)
    return _orchestrator
