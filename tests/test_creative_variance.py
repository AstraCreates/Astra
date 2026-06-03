from backend.core.creative import build_creative_brief
from backend.tools.design_tools import generate_color_palette, generate_design_spec, generate_logo_brief


def test_creative_brief_varies_by_session_for_same_prompt():
    prompt = "Build an AI sales copilot for founders"

    first = build_creative_brief("session_a", prompt)
    second = build_creative_brief("session_b", prompt)

    assert first["creative_seed"] != second["creative_seed"]
    assert (
        first["archetype"],
        first["motif"],
        first["design_instruction"],
    ) != (
        second["archetype"],
        second["motif"],
        second["design_instruction"],
    )


def test_creative_brief_is_stable_within_session():
    prompt = "Build an AI sales copilot for founders"

    first = build_creative_brief("session_a", prompt)
    second = build_creative_brief("session_a", prompt)

    assert first == second


def test_design_tools_resolve_descriptive_creative_vibes():
    palette = generate_color_palette(vibe="Premium Studio direction with luxury editorial surfaces")
    spec = generate_design_spec(vibe="Signal Lab direction with innovative data motifs")
    brief = generate_logo_brief("TestCo", brand_vibe="Calm System with soft visual hierarchy")

    assert palette["brand_vibe"] == "luxury"
    assert any("forward-looking" in item.lower() for item in spec["design_principles"])
    assert brief["direction"].startswith("Soft colors")
