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
            "1. obsidian_read(agent='design') — ONE call only. Read whatever notes exist for the design agent.\n"
            "   Extract colors, fonts, brand_vibe, hex values from the result.\n"
            "   If notes are empty or missing, proceed immediately using goal context for design direction.\n"
            "   Do NOT call obsidian_read a second time regardless of the result.\n"
            "2. generate_landing_page_html(\n"
            "     page_title=<company name>,\n"
            "     headline=<sharp 6-10 word headline matching brand voice from design spec>,\n"
            "     subheadline=<one sentence value prop>,\n"
            "     value_props=<list of 4-6 specific feature/benefit strings>,\n"
            "     cta_text=<action CTA>,\n"
            "     cta_url='#waitlist',\n"
            "     company_name=<company name>,\n"
            "     business_context=<2-3 sentence product summary + EXACT colors/fonts/brand_vibe from design spec>\n"
            "   )\n"
            "   CRITICAL: Copy the exact hex colors and font names from the design spec into business_context.\n"
            "   The generated page MUST use those colors — not defaults.\n"
            "   Use SPECIFIC copy — real product name, real metrics, real benefits from the goal.\n"
            "3. vercel_deploy(project_slug=<company-landing>, html=<html from step 2>)\n"
            "4. obsidian_log — log the live Vercel URL\n"
            "5. done — return {url: <live Vercel URL>}\n\n"
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
