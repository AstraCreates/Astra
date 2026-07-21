import pytest

from backend.tools._llm import parse_json_response


def test_parses_plain_json():
    assert parse_json_response('{"action": "answer", "reply": "hi"}') == {"action": "answer", "reply": "hi"}


def test_strips_markdown_fence():
    raw = '```json\n{"title": "Foo", "content": "bar"}\n```'
    assert parse_json_response(raw) == {"title": "Foo", "content": "bar"}


def test_ignores_trailing_prose_after_the_json_object():
    # This exact shape (valid JSON immediately followed by trailing model
    # commentary) is what broke company_os_copilot's turn classifier and
    # company_os_runner's document synthesis in production: a naive
    # text.find('{')..text.rfind('}') slice grabs a brace inside the
    # trailing text and produces "Extra data" on a fully valid JSON prefix.
    raw = '{"action": "new", "initiative_id": null, "reply": "On it."}\n\nLet me know if you need anything else!'
    assert parse_json_response(raw) == {"action": "new", "initiative_id": None, "reply": "On it."}


def test_ignores_trailing_text_that_itself_contains_a_brace():
    raw = '{"title": "Foo", "content": "bar"} note: {see also file.py}'
    assert parse_json_response(raw) == {"title": "Foo", "content": "bar"}


def test_raises_on_no_json_object():
    with pytest.raises(ValueError):
        parse_json_response("not json at all")
