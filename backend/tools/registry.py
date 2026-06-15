"""
Tool registry. Maps tool names to sync callables.
All tools must be sync (AstraAgent wraps execution in asyncio.to_thread).
"""
from backend.tools.hunter_tools import (
    hunter_domain_search,
    hunter_find_email,
    hunter_verify_email,
    hunter_enrich_company,
    hunter_enrich_person,
    hunter_enrich_combined,
    hunter_search_by_domains,
    hunter_store_contacts,
)
from backend.tools.apollo_tools import (
    apollo_search_people,
    apollo_search_companies,
    apollo_enrich_person,
    apollo_enrich_batch,
)
from backend.tools.web_search import web_search, news_search
from backend.tools.patent_search import patent_search
from backend.tools.vercel_deploy import vercel_deploy, generate_landing_page_html
from backend.tools.github_scaffold import github_create_repo
from backend.tools.social_content import generate_reel_package, generate_tiktok_package, generate_meta_ad
from backend.tools.email_campaign import send_email_campaign, build_email_html
from backend.tools.pdf_generator import generate_pdf
from backend.tools.doc_generator import format_legal_document
from backend.tools.composio_tools import (
    composio_gmail_send,
    gmail_send_direct,
    gmail_list_messages,
    gmail_get_message,
    composio_linkedin_post,
    composio_github_create_pr,
    composio_github_create_issue,
    composio_linear_create_issue,
    composio_calendar_create_event,
    composio_notion_create_page,
)
from backend.tools.company_brain import (
    add_company_brain_record,
    ask_company_brain,
    company_brain_agent_context,
    configure_company_brain_sync,
    get_company_brain_sync_status,
    ingest_company_brain_records,
    run_due_company_brain_syncs,
    maintain_company_brain,
    run_company_brain_sync,
    search_company_brain,
    sync_company_brain,
)
from backend.tools.company_brain_connectors import import_company_brain_source, import_company_brain_sources
from backend.tools.contact_scraper import (
    bulk_discover_and_store,
    search_local_contacts,
    scrape_company_contacts,
    get_github_org_contacts,
    get_hn_hiring_contacts,
    discover_via_web_search,
)
from backend.tools.klaviyo_tools import (
    klaviyo_create_list,
    klaviyo_add_to_list,
    klaviyo_create_campaign,
    klaviyo_get_metrics,
)
from backend.tools.twilio_tools import (
    twilio_send_sms,
    twilio_send_bulk_sms,
    twilio_create_messaging_service,
    twilio_get_usage,
)
from backend.tools.square_tools import (
    square_list_services,
    square_create_service,
    square_create_booking,
    square_list_bookings,
    square_get_revenue,
)
from backend.tools.printful_tools import (
    printful_get_products,
    printful_create_store_product,
    printful_get_orders,
    printful_create_order,
)
from backend.tools.yelp_tools import (
    yelp_search_businesses,
    yelp_get_business,
    yelp_get_reviews,
    yelp_search_categories,
)
from backend.tools.web_tasks import run_web_task
from backend.tools.examples_library import search_examples, list_example_categories
from backend.tools.lemonsqueezy_tools import (
    ls_create_product,
    ls_get_sales,
    ls_create_discount,
)

TOOL_REGISTRY: dict[str, callable] = {
    # Research
    "web_search": web_search,
    "news_search": news_search,
    "patent_search": patent_search,

    # Web
    "vercel_deploy": vercel_deploy,
    "generate_landing_page_html": generate_landing_page_html,

    # Technical
    "github_create_repo": github_create_repo,

    # Marketing
    "generate_reel_package": generate_reel_package,
    "generate_tiktok_package": generate_tiktok_package,
    "generate_meta_ad": generate_meta_ad,
    "send_email_campaign": send_email_campaign,
    "build_email_html": build_email_html,

    # Legal / docs
    "generate_pdf": generate_pdf,
    "format_legal_document": format_legal_document,

    # Composio — OAuth-backed (Gmail, LinkedIn, GitHub PR, Linear, Calendar, Notion)
    "composio_gmail_send": composio_gmail_send,
    "gmail_send_direct": gmail_send_direct,
    "gmail_list_messages": gmail_list_messages,
    "gmail_get_message": gmail_get_message,
    "composio_linkedin_post": composio_linkedin_post,
    "composio_github_create_pr": composio_github_create_pr,
    "composio_github_create_issue": composio_github_create_issue,
    "composio_linear_create_issue": composio_linear_create_issue,
    "composio_calendar_create_event": composio_calendar_create_event,
    "composio_notion_create_page": composio_notion_create_page,

    # Outreach — local scraper DB (free, no API needed)
    "bulk_discover_and_store": bulk_discover_and_store,
    "search_local_contacts": search_local_contacts,
    "scrape_company_contacts": scrape_company_contacts,
    "get_github_org_contacts": get_github_org_contacts,
    "get_hn_hiring_contacts": get_hn_hiring_contacts,
    "discover_via_web_search": discover_via_web_search,

    # Outreach — Hunter.io (domain search + enrichment + composite store)
    "hunter_domain_search": hunter_domain_search,
    "hunter_find_email": hunter_find_email,
    "hunter_verify_email": hunter_verify_email,
    "hunter_enrich_company": hunter_enrich_company,
    "hunter_enrich_person": hunter_enrich_person,
    "hunter_enrich_combined": hunter_enrich_combined,
    "hunter_search_by_domains": hunter_search_by_domains,
    "hunter_store_contacts": hunter_store_contacts,
    "apollo_search_people": apollo_search_people,
    "apollo_search_companies": apollo_search_companies,
    "apollo_enrich_person": apollo_enrich_person,
    "apollo_enrich_batch": apollo_enrich_batch,

    # Company brain — normalized cross-tool context for humans and agents
    "company_brain_search": search_company_brain,
    "company_brain_sync": sync_company_brain,
    "company_brain_add_record": add_company_brain_record,
    "company_brain_ingest_records": ingest_company_brain_records,
    "company_brain_maintain": maintain_company_brain,
    "company_brain_agent_context": company_brain_agent_context,
    "company_brain_ask": ask_company_brain,
    "company_brain_configure_sync": configure_company_brain_sync,
    "company_brain_sync_status": get_company_brain_sync_status,
    "company_brain_run_sync": run_company_brain_sync,
    "company_brain_run_due_syncs": run_due_company_brain_syncs,
    "company_brain_import_source": import_company_brain_source,
    "company_brain_import_sources": import_company_brain_sources,

    # Ecommerce — Klaviyo email marketing
    "klaviyo_create_list": klaviyo_create_list,
    "klaviyo_add_to_list": klaviyo_add_to_list,
    "klaviyo_create_campaign": klaviyo_create_campaign,
    "klaviyo_get_metrics": klaviyo_get_metrics,

    # Ecommerce — Printful print-on-demand
    "printful_get_products": printful_get_products,
    "printful_create_store_product": printful_create_store_product,
    "printful_get_orders": printful_get_orders,
    "printful_create_order": printful_create_order,

    # Ecommerce — Lemon Squeezy digital products
    "ls_create_product": ls_create_product,
    "ls_get_sales": ls_get_sales,
    "ls_create_discount": ls_create_discount,

    # Local service — Square POS + appointments
    "square_list_services": square_list_services,
    "square_create_service": square_create_service,
    "square_create_booking": square_create_booking,
    "square_list_bookings": square_list_bookings,
    "square_get_revenue": square_get_revenue,

    # Local service — Twilio SMS
    "twilio_send_sms": twilio_send_sms,
    "twilio_send_bulk_sms": twilio_send_bulk_sms,
    "twilio_create_messaging_service": twilio_create_messaging_service,
    "twilio_get_usage": twilio_get_usage,

    # Local service — Yelp competitor/market research
    "yelp_search_businesses": yelp_search_businesses,
    "yelp_get_business": yelp_get_business,
    "yelp_get_reviews": yelp_get_reviews,
    "yelp_search_categories": yelp_search_categories,

    # Website operator
    "run_web_task": run_web_task,

    # Examples library — searchable code patterns and templates for all agents
    "search_examples": search_examples,
    "list_example_categories": list_example_categories,
}


def execute_tool(tool_name: str, tool_input: dict) -> dict:
    """Execute a registered tool. Returns result dict."""
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool '{tool_name}'. Available: {list(TOOL_REGISTRY.keys())}"}
    try:
        result = fn(**tool_input)
        return result if isinstance(result, dict) else {"result": result}
    except TypeError as e:
        return {"error": f"Tool '{tool_name}' called with wrong args: {e}"}
    except Exception as e:
        return {"error": f"Tool '{tool_name}' execution failed: {e}"}
