"""
Tool registry. Maps tool names to sync callables.
All tools must be sync (AstraAgent wraps execution in asyncio.to_thread).
"""
from backend.tools.web_search import web_search, news_search
from backend.tools.patent_search import patent_search
from backend.tools.vercel_deploy import vercel_deploy, generate_landing_page_html
from backend.tools.github_scaffold import github_create_repo
from backend.tools.social_content import generate_reel_package, generate_tiktok_package, generate_meta_ad
from backend.tools.email_campaign import send_email_campaign, build_email_html
from backend.tools.pdf_generator import generate_pdf

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

    # Legal
    "generate_pdf": generate_pdf,
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
