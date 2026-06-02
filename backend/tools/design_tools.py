"""Design tools — wireframes, mockups, color palettes, design specs, asset generation."""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def generate_wireframe(
    page_type: str = "",
    sections: list = None,
    style: str = "minimal",
    target_audience: str = "",
    # aliases the LLM commonly uses
    page: str = "",
    layout_description: str = "",
    brand_vibe: str = "",
    **kwargs,
) -> dict:
    """
    Generate an ASCII wireframe + component spec for a web/app page.
    page_type: landing | dashboard | onboarding | pricing | settings | about
    style: minimal | corporate | startup | bold
    """
    page_type = page_type or page or "landing"
    if brand_vibe and style == "minimal":
        style = brand_vibe
    if sections is None:
        sections = [layout_description] if layout_description else []

    templates = {
        "landing": _landing_wireframe,
        "dashboard": _dashboard_wireframe,
        "onboarding": _onboarding_wireframe,
        "pricing": _pricing_wireframe,
        "settings": _settings_wireframe,
    }

    builder = templates.get(page_type, _generic_wireframe)
    wireframe = builder(sections, style, target_audience)

    return {
        "page_type": page_type,
        "style": style,
        "wireframe_ascii": wireframe["ascii"],
        "components": wireframe["components"],
        "copy_guidelines": wireframe["copy_guidelines"],
        "accessibility_notes": [
            "All images need alt text",
            "Color contrast ratio >= 4.5:1 for body text",
            "Interactive elements min 44x44px touch target",
            "Skip-to-content link at top of page",
        ],
    }


def generate_color_palette(
    brand_vibe: str = "minimal",
    industry: str = "",
    primary_hex: str = "",
    brand_name: str = "",  # alias — model sometimes passes brand_name instead of brand_vibe
    **kwargs,
) -> dict:
    if not brand_vibe or brand_vibe == "minimal":
        brand_vibe = brand_name or "minimal"
    """
    Generate a complete brand color palette with usage guidelines.
    brand_vibe: bold | minimal | friendly | professional | innovative | calm
    """
    # Fallback lookup table (used only if LLM call fails)
    _fallback_palettes = {
        "bold": {
            "primary": primary_hex or "#FF3B30",
            "secondary": "#FF9500",
            "accent": "#34C759",
            "background": "#000000",
            "surface": "#1C1C1E",
            "text_primary": "#FFFFFF",
            "text_secondary": "#8E8E93",
            "border": "#3A3A3C",
        },
        "minimal": {
            "primary": primary_hex or "#000000",
            "secondary": "#6B7280",
            "accent": "#3B82F6",
            "background": "#FFFFFF",
            "surface": "#F9FAFB",
            "text_primary": "#111827",
            "text_secondary": "#6B7280",
            "border": "#E5E7EB",
        },
        "friendly": {
            "primary": primary_hex or "#7C3AED",
            "secondary": "#EC4899",
            "accent": "#F59E0B",
            "background": "#FAFAFA",
            "surface": "#FFFFFF",
            "text_primary": "#1F2937",
            "text_secondary": "#6B7280",
            "border": "#E5E7EB",
        },
        "professional": {
            "primary": primary_hex or "#1E3A5F",
            "secondary": "#2563EB",
            "accent": "#059669",
            "background": "#FFFFFF",
            "surface": "#F8FAFC",
            "text_primary": "#0F172A",
            "text_secondary": "#64748B",
            "border": "#CBD5E1",
        },
        "innovative": {
            "primary": primary_hex or "#6366F1",
            "secondary": "#EC4899",
            "accent": "#14B8A6",
            "background": "#030712",
            "surface": "#111827",
            "text_primary": "#F9FAFB",
            "text_secondary": "#9CA3AF",
            "border": "#1F2937",
        },
        "calm": {
            "primary": primary_hex or "#0EA5E9",
            "secondary": "#10B981",
            "accent": "#F59E0B",
            "background": "#F0F9FF",
            "surface": "#FFFFFF",
            "text_primary": "#0C4A6E",
            "text_secondary": "#0369A1",
            "border": "#BAE6FD",
        },
    }

    # Attempt LLM-generated contextual palette
    palette = None
    try:
        from backend.tools._llm import generate as _llm_generate
        prompt = (
            f"You are a brand color expert. Generate a color palette for:\n"
            f"Brand name: {brand_name or '(not specified)'}\n"
            f"Industry: {industry or '(not specified)'}\n"
            f"Brand vibe: {brand_vibe}\n"
            f"Primary color override: {primary_hex or '(none — choose the best primary)'}\n\n"
            f"Return ONLY a JSON object with exactly these keys: "
            f"primary, secondary, accent, background, surface, text_primary, text_secondary, border. "
            f"Values must be hex color codes (e.g. #1A2B3C). "
            f"Ensure sufficient contrast ratios. "
            f"{'Use ' + primary_hex + ' as the primary color.' if primary_hex else ''} "
            f"Match the brand vibe and industry appropriately."
        )
        raw = _llm_generate(prompt, max_tokens=300, json_mode=True, model="fast", temperature=0.5)
        parsed = json.loads(raw)
        # Validate all required keys are present and look like hex colors
        required_keys = {"primary", "secondary", "accent", "background", "surface", "text_primary", "text_secondary", "border"}
        if required_keys.issubset(parsed.keys()) and all(
            isinstance(parsed[k], str) and parsed[k].startswith("#") and len(parsed[k]) in (4, 7)
            for k in required_keys
        ):
            palette = {k: parsed[k] for k in required_keys}
            if primary_hex:
                palette["primary"] = primary_hex
    except Exception as e:
        logger.warning("LLM color palette generation failed, using fallback: %s", e)

    if palette is None:
        palette = _fallback_palettes.get(brand_vibe, _fallback_palettes["minimal"])
        if primary_hex:
            palette["primary"] = primary_hex

    return {
        "brand_vibe": brand_vibe,
        "industry": industry,
        "colors": palette,
        "css_variables": "\n".join(f"  --color-{k.replace('_', '-')}: {v};" for k, v in palette.items()),
        "tailwind_config": {k.replace("_", "-"): v for k, v in palette.items()},
        "usage_guidelines": {
            "primary": "Main CTAs, links, brand elements. Use sparingly (10% of page).",
            "secondary": "Supporting UI elements, secondary buttons.",
            "accent": "Highlights, badges, success states.",
            "background": "Page background.",
            "surface": "Cards, modals, sidebars.",
            "text_primary": "Headings, body text.",
            "text_secondary": "Captions, helper text, placeholders.",
            "border": "Dividers, input borders.",
        },
    }


def generate_design_spec(
    product_name: str = "",
    product_type: str = "saas",
    target_audience: str = "founders",
    brand_vibe: str = "minimal",
    key_screens: list = None,
    brand_name: str = "",   # alias for product_name
    palette: dict = None,   # accepted but ignored (color palette already separate)
    vibe: str = "",         # alias for brand_vibe
    fonts: list = None,     # accepted for context, not used structurally
    **kwargs,
) -> dict:
    """
    Generate a complete design specification document for a product.
    product_type: saas | marketplace | mobile_app | dashboard | ecommerce
    """
    if brand_name and not product_name:
        product_name = brand_name
    if vibe and brand_vibe == "minimal":
        brand_vibe = vibe
    screens = key_screens or _default_screens(product_type)

    return {
        "product": product_name,
        "product_type": product_type,
        "target_audience": target_audience,
        "design_principles": _design_principles(brand_vibe),
        "typography": _typography_spec(brand_vibe, brand_name=product_name, industry=product_type),
        "spacing_system": {
            "base_unit": "4px",
            "scale": [4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96],
            "container_max_width": "1280px",
            "content_max_width": "800px",
        },
        "component_library": _component_spec(brand_vibe),
        "key_screens": [
            {
                "name": s,
                "priority": "P1" if i < 3 else "P2",
                "user_goal": _screen_goal(s),
                "key_elements": _screen_elements(s),
            }
            for i, s in enumerate(screens)
        ],
        "responsive_breakpoints": {
            "mobile": "375px",
            "tablet": "768px",
            "desktop": "1280px",
            "wide": "1536px",
        },
        "animation_guidelines": {
            "duration_fast": "150ms",
            "duration_normal": "250ms",
            "duration_slow": "400ms",
            "easing": "cubic-bezier(0.4, 0, 0.2, 1)",
            "use_for": ["hover states", "page transitions", "modal open/close", "loading states"],
        },
    }


def generate_logo_brief(
    company_name: str,
    tagline: str = "",
    industry: str = "",
    brand_vibe: str = "minimal",
    competitors_to_avoid: list = None,
) -> dict:
    """
    Generate a logo design brief for a designer or AI image generator.
    """
    if isinstance(competitors_to_avoid, str):
        competitors_to_avoid = [c.strip() for c in competitors_to_avoid.split(",") if c.strip()]
    style_directions = {
        "minimal": "Clean wordmark or lettermark. Geometric sans-serif. No gradients.",
        "bold": "Strong icon + wordmark. High contrast. Can use thick strokes.",
        "friendly": "Rounded shapes, approachable icon, warm colors.",
        "professional": "Classic serif or geometric sans. Icon optional. Conservative.",
        "innovative": "Abstract mark, modern typeface, can use gradients sparingly.",
    }

    return {
        "company_name": company_name,
        "tagline": tagline,
        "industry": industry,
        "direction": style_directions.get(brand_vibe, style_directions["minimal"]),
        "deliverables": [
            "Primary logo (horizontal): SVG + PNG @1x, @2x, @3x",
            "Icon-only mark: SVG + PNG @1x, @2x, @3x",
            "Wordmark only: SVG + PNG @1x, @2x",
            "Favicon: 16x16, 32x32, 180x180 (Apple touch) ICO + PNG",
            "Dark variant (white on dark): all above formats",
            "OG image template: 1200x630px",
        ],
        "avoid": (competitors_to_avoid or []) + [
            "Stock icon clipart",
            "Drop shadows",
            "More than 2 colors in primary lockup",
            "Raster formats as primary",
        ],
        "prompts_for_ai_generation": [
            f"minimalist logo for '{company_name}', {brand_vibe} style, {industry} industry, vector, clean, professional, white background",
            f"logo design '{company_name}' {brand_vibe} geometric mark, no text, SVG style, simple, scalable",
        ],
    }


def _wireframe_llm_description(page_type: str, sections, style: str, audience: str) -> str:
    """Call LLM to generate a contextual layout description for a page."""
    try:
        from backend.tools._llm import generate as _llm_generate
        sections_str = ", ".join(sections) if sections else "standard sections"
        prompt = (
            f"You are a UX designer writing a concise wireframe description.\n"
            f"Page type: {page_type}\n"
            f"Style: {style}\n"
            f"Target audience: {audience or 'general users'}\n"
            f"Sections to include: {sections_str}\n\n"
            f"Write 2-4 sentences describing the page layout, visual hierarchy, key UI zones, "
            f"and how the sections are arranged. Be specific and practical — mention placement "
            f"(top, left sidebar, hero area, grid, etc.), component types, and how the style "
            f"influences the layout. Do not use ASCII art. Plain prose only."
        )
        return _llm_generate(prompt, max_tokens=200, model="fast", temperature=0.6)
    except Exception as e:
        logger.warning("LLM wireframe description failed for %s: %s", page_type, e)
        return f"{page_type.capitalize()} page layout with {style} style for {audience or 'general users'}."


def _landing_wireframe(sections, style, audience):
    description = _wireframe_llm_description("landing", sections, style, audience)
    return {
        "ascii": description,
        "components": ["NavBar", "HeroSection", "SocialProof", "FeatureGrid", "HowItWorks", "Testimonials", "Pricing", "FAQ", "Footer"],
        "copy_guidelines": {
            "headline": "Problem-focused, outcome-driven, max 8 words",
            "subheadline": "Clarify who it's for and main benefit, max 15 words",
            "cta": "Action verb + outcome (e.g. 'Start Building Free')",
        },
    }


def _dashboard_wireframe(sections, style, audience):
    description = _wireframe_llm_description("dashboard", sections, style, audience)
    return {
        "ascii": description,
        "components": ["Sidebar", "TopNav", "MetricCards", "ChartArea", "DataTable", "ActivityFeed"],
        "copy_guidelines": {
            "metric_labels": "Short, clear. Show delta vs previous period.",
            "empty_states": "Explain how to populate this section.",
        },
    }


def _onboarding_wireframe(sections, style, audience):
    description = _wireframe_llm_description("onboarding", sections, style, audience)
    return {
        "ascii": description,
        "components": ["ProgressBar", "StepForm", "InputFields", "ContinueButton"],
        "copy_guidelines": {
            "heading": "Warm, personal. Use their name if available.",
            "labels": "Short nouns. No 'please' or 'enter your'.",
            "cta": "'Continue' not 'Next'. Last step: 'Get Started' or 'Launch'.",
        },
    }


def _pricing_wireframe(sections, style, audience):
    description = _wireframe_llm_description("pricing", sections, style, audience)
    return {
        "ascii": description,
        "components": ["PricingToggle", "PricingCards", "FeatureComparison", "PricingFAQ"],
        "copy_guidelines": {
            "tier_names": "Name tiers after outcomes, not features (e.g. 'Starter' vs 'Free')",
            "features": "Positive framing — list what's included, not what's missing",
        },
    }


def _settings_wireframe(sections, style, audience):
    description = _wireframe_llm_description("settings", sections, style, audience)
    return {
        "ascii": description,
        "components": ["SettingsSidebar", "SettingsPanel", "FormFields", "SaveButton", "DangerZone"],
        "copy_guidelines": {
            "danger_zone": "Clear warning copy. Destructive actions require confirm step.",
        },
    }


def _generic_wireframe(sections, style, audience):
    ascii_art = "\n".join(
        [f"┌{'─' * 40}┐"]
        + [f"│  {s:<38}│" for s in (sections or ["Section 1", "Section 2", "Section 3"])]
        + [f"└{'─' * 40}┘"]
    )
    return {"ascii": ascii_art, "components": sections or [], "copy_guidelines": {}}


def _design_principles(vibe: str) -> list:
    base = ["Content first — layout serves content, not the other way around",
            "Consistent spacing — use 4px grid throughout",
            "Progressive disclosure — show what's needed, hide complexity"]
    extras = {
        "minimal": ["Every pixel earns its place — remove anything decorative",
                    "White space is not empty space — it's breathing room"],
        "bold": ["High contrast creates hierarchy", "Motion should communicate, not decorate"],
        "friendly": ["Rounded corners and soft colors build trust",
                     "Friendly microcopy at every friction point"],
    }
    return base + extras.get(vibe, [])


def _typography_spec(vibe: str, brand_name: str = "", industry: str = "") -> dict:
    _fallback_fonts = {
        "minimal": {"heading": "Syne", "body": "DM Sans", "mono": "JetBrains Mono"},
        "bold": {"heading": "Bebas Neue", "body": "Manrope", "mono": "Fira Code"},
        "friendly": {"heading": "Nunito", "body": "Plus Jakarta Sans", "mono": "JetBrains Mono"},
        "professional": {"heading": "Fraunces", "body": "Source Sans 3", "mono": "Source Code Pro"},
        "innovative": {"heading": "Space Grotesk", "body": "DM Sans", "mono": "JetBrains Mono"},
        "calm": {"heading": "Playfair Display", "body": "Lato", "mono": "JetBrains Mono"},
        "energetic": {"heading": "Unbounded", "body": "Manrope", "mono": "Fira Code"},
    }

    heading_font = None
    body_font = None
    try:
        from backend.tools._llm import generate as _llm_generate
        prompt = (
            f"You are a typography expert. Choose Google Fonts for a brand:\n"
            f"Brand name: {brand_name or '(not specified)'}\n"
            f"Industry: {industry or '(not specified)'}\n"
            f"Brand vibe: {vibe}\n\n"
            f"Pick distinctive, appropriate Google Fonts. "
            f"Avoid Inter, Poppins, and Roboto — use more characterful choices. "
            f"Return ONLY a JSON object with exactly two keys: heading_font and body_font. "
            f"Values must be valid Google Fonts names (e.g. 'Syne', 'DM Sans', 'Fraunces', 'Space Grotesk'). "
            f"The pairing should feel cohesive and appropriate for the brand vibe and industry."
        )
        raw = _llm_generate(prompt, max_tokens=100, json_mode=True, model="fast", temperature=0.6)
        parsed = json.loads(raw)
        if "heading_font" in parsed and "body_font" in parsed:
            heading_font = str(parsed["heading_font"]).strip()
            body_font = str(parsed["body_font"]).strip()
    except Exception as e:
        logger.warning("LLM typography selection failed, using fallback: %s", e)

    if not heading_font or not body_font:
        f = _fallback_fonts.get(vibe, _fallback_fonts["minimal"])
        heading_font = f["heading"]
        body_font = f["body"]

    mono_font = _fallback_fonts.get(vibe, _fallback_fonts["minimal"])["mono"]

    return {
        "heading_font": heading_font,
        "body_font": body_font,
        "mono_font": mono_font,
        "scale": {
            "xs": "12px / 1.4",
            "sm": "14px / 1.5",
            "base": "16px / 1.6",
            "lg": "18px / 1.5",
            "xl": "20px / 1.4",
            "2xl": "24px / 1.3",
            "3xl": "30px / 1.2",
            "4xl": "36px / 1.1",
            "5xl": "48px / 1.05",
        },
        "weights": {"normal": 400, "medium": 500, "semibold": 600, "bold": 700},
    }


def _component_spec(vibe: str) -> dict:
    radius = {"minimal": "6px", "bold": "4px", "friendly": "12px", "professional": "4px", "innovative": "8px"}
    return {
        "border_radius": radius.get(vibe, "6px"),
        "button": {
            "primary": "Filled, primary color bg, white text",
            "secondary": "Outlined, border only, primary text",
            "ghost": "No border, no bg, primary text",
            "sizes": {"sm": "32px h, 12px px", "md": "40px h, 16px px", "lg": "48px h, 24px px"},
        },
        "input": {
            "height": "40px",
            "border": "1px solid border-color",
            "focus": "2px ring, primary color",
            "error": "red border + error message below",
        },
        "card": {"padding": "24px", "border": "1px solid border-color", "shadow": "sm"},
        "modal": {"max_width": "480px", "backdrop": "rgba(0,0,0,0.5)"},
    }


def _default_screens(product_type: str) -> list:
    screens = {
        "saas": ["Landing", "Sign Up", "Onboarding", "Dashboard", "Settings", "Billing"],
        "marketplace": ["Home", "Search/Browse", "Listing Detail", "Checkout", "Dashboard", "Profile"],
        "dashboard": ["Overview", "Analytics", "Reports", "Settings", "Team", "Notifications"],
        "ecommerce": ["Home", "Product Listing", "Product Detail", "Cart", "Checkout", "Order Confirmation"],
        "mobile_app": ["Splash", "Onboarding", "Home", "Detail View", "Profile", "Settings"],
    }
    return screens.get(product_type, ["Home", "Main View", "Detail", "Settings"])


def _screen_goal(screen: str) -> str:
    goals = {
        "Landing": "Convince visitor to sign up",
        "Sign Up": "Capture email + create account with minimal friction",
        "Onboarding": "Get user to first value moment as fast as possible",
        "Dashboard": "Show user their key metrics at a glance",
        "Settings": "Let user customize without overwhelming",
        "Billing": "Upgrade or manage plan without anxiety",
    }
    return goals.get(screen, f"User completes core {screen.lower()} task")


def _screen_elements(screen: str) -> list:
    elements = {
        "Landing": ["Hero section", "Social proof", "Feature highlights", "CTA"],
        "Sign Up": ["Email field", "Password field", "OAuth buttons", "Terms checkbox"],
        "Onboarding": ["Progress indicator", "Step form", "Skip option", "Completion celebration"],
        "Dashboard": ["Metric cards", "Primary chart", "Recent activity", "Quick actions"],
        "Settings": ["Nav sections", "Form fields", "Save button", "Danger zone"],
        "Billing": ["Current plan", "Usage meter", "Upgrade options", "Invoice history"],
    }
    return elements.get(screen, ["Primary content", "Actions", "Navigation"])
