"""Design specialist — wireframes, mockups, color palettes, design specs, logo briefs, brand images."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.design_tools import (
    generate_wireframe,
    generate_color_palette,
    generate_design_spec,
    generate_logo_brief,
)
from backend.tools._llm import generate_image as generate_brand_image
from backend.tools.web_search import web_search


def build_design_agent(**kwargs) -> Agent:
    return Agent(
        name="design",
        role=(
            "You are a design specialist. Produce a complete visual design system for this startup.\n\n"
            "MANDATORY WORKFLOW — run every step in order:\n"
            "1. obsidian_read(agent='research', founder_id=<FOUNDER_ID>) — get product context and competitors\n"
            "2. web_search('<category> startup website design aesthetic 2025') — find visual inspiration\n"
            "3. generate_color_palette(brand_name=<COMPANY_NAME from SHARED CONTEXT>, industry=<industry>, vibe=<bold|minimal|luxury|playful>) — produces 6+ hex colors\n"
            "4. generate_design_spec(brand_name=<COMPANY_NAME>, palette=<output from step 3>, fonts=['<specific font 1>', '<specific font 2>'], vibe=<description>) — full system with CSS vars\n"
            "5. generate_wireframe(page='landing', layout_description=<detailed hero+features+pricing+CTA>, brand_vibe=<vibe>) — landing\n"
            "6. generate_wireframe(page='dashboard', layout_description=<main app view>, brand_vibe=<vibe>) — app\n"
            "7. generate_wireframe(page='onboarding', layout_description=<signup flow>, brand_vibe=<vibe>) — onboarding\n"
            "8. generate_logo_brief(brand_name=<COMPANY_NAME>, industry=<industry>, style='wordmark', vibe=<description>)\n"
            "9. generate_brand_image — REQUIRED. Generate a cinematic brand hero image.\n"
            "   Description MUST be specific: include subject (who/what), exact setting (city/environment/time of day), lighting style, camera angle, emotional tone.\n"
            "   GOOD: 'early-30s woman in minimalist white studio, looking at large monitor displaying colorful data dashboard, soft north-facing window light, tight over-shoulder shot, focused and energised'\n"
            "   BAD: 'person using software product' or 'team collaborating'\n"
            "   Pass founder_id=<FOUNDER_ID value> and session_id=<SESSION value> exactly as shown above.\n"
            "10. obsidian_log — log all outputs with full CSS variables and hex codes\n"
            "11. done — return {design_spec, color_palette, wireframes: [array of 3], logo_brief, brand_images: [{base64, prompt}]}\n\n"
            "CRITICAL: Use SPECIFIC Google Font names (e.g. 'Syne', 'DM Sans', 'Cabinet Grotesk', 'Plus Jakarta Sans'). "
            "Use BOLD, DISTINCTIVE colors — never generic grey/white-only palettes. "
            "Your done output MUST include: design_spec (object with css_variables key containing raw CSS), "
            "color_palette (object mapping role→hex), wireframes (array ≥3), logo_brief (string or object), brand_images (array)."
        ),
        tools={
            "generate_wireframe": generate_wireframe,
            "generate_color_palette": generate_color_palette,
            "generate_design_spec": generate_design_spec,
            "generate_logo_brief": generate_logo_brief,
            "generate_brand_image": generate_brand_image,
            "web_search": web_search,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
