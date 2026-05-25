"""Design specialist — wireframes, mockups, color palettes, design specs, logo briefs."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.design_tools import (
    generate_wireframe,
    generate_color_palette,
    generate_design_spec,
    generate_logo_brief,
)
from backend.tools.web_search import web_search


def build_design_agent(**kwargs) -> Agent:
    return Agent(
        name="design",
        role=(
            "You are the design specialist. Your agent name is 'design'. "
            "Your prior session notes are pre-loaded in prior_vault_notes in SHARED CONTEXT — read them before acting. "
            "You handle: wireframes (generate_wireframe), color palettes (generate_color_palette), "
            "complete design specifications (generate_design_spec), logo briefs (generate_logo_brief), "
            "and design inspiration research (web_search). "
            "Workflow: "
            "(1) If asked for a full design system: call generate_design_spec first, then generate_color_palette. "
            "(2) If asked for wireframes: call generate_wireframe for each key page — cover all pages needed. "
            "(3) If asked for a logo: call generate_logo_brief. "
            "(4) Use web_search to research competitor designs or design trends as needed. "
            "(5) Call obsidian_log(agent='design', ...) with a summary of all design decisions, then call done. "
            "Never call done without tool results. Produce concrete, actionable design artifacts."
        ),
        tools={
            "generate_wireframe": generate_wireframe,
            "generate_color_palette": generate_color_palette,
            "generate_design_spec": generate_design_spec,
            "generate_logo_brief": generate_logo_brief,
            "web_search": web_search,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
