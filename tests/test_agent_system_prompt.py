import sys
import types

sys.modules.setdefault("openai", types.SimpleNamespace(OpenAI=object))

from backend.core.agent import Agent


def _sample_tool(industry: str = "", job_title: str = "owner", location: str = ""):
    """Find companies matching the requested filters."""
    return {"industry": industry, "job_title": job_title, "location": location}


def _secondary_tool(query: str, limit: int = 5):
    """Search for supporting evidence."""
    return {"query": query, "limit": limit}


def _old_sig(name, fn) -> str:
    import inspect

    try:
        sig = inspect.signature(fn)
        params = ", ".join(
            f"{pname}={repr(param.default)}" if param.default is not inspect.Parameter.empty else pname
            for pname, param in sig.parameters.items()
        )
        doc = (fn.__doc__ or "").split("\n")[0].strip()
        return f"  - {name}({params})\n    {doc}"
    except Exception:
        return f"  - {name}: {fn.__doc__ or ''}"


def test_system_prompt_tool_signature_dump_is_shorter_but_preserves_tool_info():
    agent = Agent(
        name="research",
        role="You are a specialist.\n\nTOOLS:\n- Preserve this handwritten guidance exactly.",
        tools={"find_leads": _sample_tool, "search_evidence": _secondary_tool},
    )

    prompt = agent._system_prompt()
    tool_section = prompt.rsplit("TOOLS:\n", 1)[1]

    assert "- Preserve this handwritten guidance exactly." in prompt
    assert "find_leads" in tool_section
    assert "search_evidence" in tool_section
    assert "industry" in tool_section
    assert "job_title" in tool_section
    assert "location" in tool_section
    assert "Find companies matching the requested filters." in tool_section
    assert "Search for supporting evidence." in tool_section

    expected_new_line = "  - find_leads(industry, job_title, location): Find companies matching the requested filters."
    assert expected_new_line in tool_section
    assert "industry=''" not in tool_section
    assert "job_title='owner'" not in tool_section
    assert "location=''" not in tool_section
    assert "\n    Find companies matching the requested filters." not in tool_section

    old_tool_list = "\n".join(
        _old_sig(name, fn) for name, fn in {"find_leads": _sample_tool, "search_evidence": _secondary_tool}.items()
    )
    new_tool_list = "\n".join(tool_section.splitlines()[:2])

    assert len(new_tool_list) < len(old_tool_list)
