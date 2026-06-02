"""Design specialist — wireframes, mockups, color palettes, design specs, logos, brand images."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.design_tools import (
    generate_wireframe,
    generate_color_palette,
    generate_design_spec,
    generate_logo_brief,
)
from backend.tools._llm import generate_brand_board, generate_logo
from backend.tools.web_search import web_search


def build_design_agent(**kwargs) -> Agent:
    return Agent(
        name="design",
        role=(
            "You are a design specialist. Produce a complete visual design system including real logo images.\n\n"
            "MANDATORY WORKFLOW — run every step in order:\n"
            "1. obsidian_read(agent='research', founder_id=<FOUNDER_ID>) — get product context\n"
            "2. web_search('<category> startup logo design 2025') — find visual inspiration\n"
            "3. generate_color_palette(brand_name=<COMPANY_NAME>, industry=<industry>, vibe=<bold|minimal|luxury|playful>)\n"
            "4. generate_design_spec(brand_name=<COMPANY_NAME>, palette=<step 3 output>, fonts=['<font1>', '<font2>'], vibe=<description>)\n"
            "5. generate_logo(brand_name=<COMPANY_NAME>, style='wordmark', colors=<primary + accent hex from palette>, vibe=<description>, founder_id=<FOUNDER_ID>, session_id=<SESSION>) — FULL logo with name\n"
            "6. generate_logo(brand_name=<COMPANY_NAME>, style='icon', colors=<primary + accent hex from palette>, vibe=<description>, founder_id=<FOUNDER_ID>, session_id=<SESSION>) — ICON only, no text\n"
            "7. generate_wireframe(page='landing', layout_description=<detailed layout>, brand_vibe=<vibe>)\n"
            "8. generate_wireframe(page='dashboard', layout_description=<main app view>, brand_vibe=<vibe>)\n"
            "9. generate_wireframe(page='onboarding', layout_description=<signup flow>, brand_vibe=<vibe>)\n"
            "10. generate_brand_board(brand_name=<COMPANY_NAME>, colors=<primary hex accent hex from palette>, vibe=<design style>, tagline=<one-line tagline>, founder_id=<FOUNDER_ID>, session_id=<SESSION>) — brand identity board with multiple graphic compositions\n"
            "11. obsidian_log — save everything including logo base64 data so marketing can use them\n"
            "12. done — return {design_spec, color_palette, wireframes, logo_wordmark: {base64, prompt}, logo_icon: {base64, prompt}, brand_images}\n\n"
            "CRITICAL: Use SPECIFIC Google Font names. Use BOLD, DISTINCTIVE colors — never grey/white-only."
        ),
        tools={
            "generate_wireframe": generate_wireframe,
            "generate_color_palette": generate_color_palette,
            "generate_design_spec": generate_design_spec,
            "generate_logo_brief": generate_logo_brief,
            "generate_logo": generate_logo,
            "generate_brand_board": generate_brand_board,
            "web_search": web_search,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
