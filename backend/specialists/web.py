"""Web specialist — generates HTML/CSS landing page and deploys to Vercel."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.vercel_deploy import vercel_deploy, generate_landing_page_html


def build_web_agent(**kwargs) -> Agent:
    return Agent(
        name="web",
        role=(
            "You are a web specialist. Generate a high-quality HTML landing page and deploy it to Vercel.\n"
            "COMPANY_NAME is in SHARED CONTEXT — use it as the brand/product name everywhere.\n\n"
            "WORKFLOW:\n"
            "1. obsidian_read(agent='web', founder_id=<FOUNDER_ID>) — get product/research context. If no notes found, proceed using goal/shared context — do NOT retry.\n"
            "2. obsidian_read(agent='design', founder_id=<FOUNDER_ID>) — get design spec. If no notes found, infer brand from goal — do NOT retry.\n"
            "3. generate_landing_page_html(\n"
            "     page_title=<company name>,\n"
            "     headline=<sharp 6-10 word headline matching brand voice from design spec>,\n"
            "     subheadline=<one sentence value prop>,\n"
            "     value_props=<list of 4-6 specific feature/benefit strings>,\n"
            "     cta_text=<action CTA>,\n"
            "     cta_url='#waitlist',\n"
            "     company_name=<company name>,\n"
            "     business_context=<2-3 sentence summary PLUS the full design spec colors/fonts/vibe from step 2>\n"
            "   )\n"
            "   CRITICAL: Pass the design agent's colors, fonts, and brand vibe into business_context so the LLM\n"
            "   can apply them. The generated page MUST use the exact hex colors from the design spec,\n"
            "   not the default dark theme. Match the brand_vibe (bold/minimal/friendly/professional/innovative/calm).\n"
            "   Use SPECIFIC copy — real product names, real metrics, real benefits from research.\n"
            "4. vercel_deploy(project_slug=<company-landing>, html=<html from step 3>)\n"
            "5. obsidian_log — log the live Vercel URL\n"
            "6. done — return {url: <live Vercel URL>}\n\n"
            "Do NOT use GitHub repos, Next.js, Claude Code scaffolding, or React. "
            "HTML + CSS only. Fast, clean, no build step."
        ),
        tools={
            "generate_landing_page_html": generate_landing_page_html,
            "vercel_deploy": vercel_deploy,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
