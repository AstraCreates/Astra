from types import SimpleNamespace

from backend.tools.intent_classifier import classify_intent


def _fake_client(content: str, finish_reason: str = "stop"):
    class _FakeClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **_kwargs):
            message = SimpleNamespace(content=content)
            choice = SimpleNamespace(message=message, finish_reason=finish_reason)
            return SimpleNamespace(choices=[choice])
    return _FakeClient()


def test_single_department_classification(monkeypatch):
    monkeypatch.setattr("backend.core.llm_client.get_or_client", lambda *_a, **_k: _fake_client(
        "what is 9router :: research"
    ))
    result = classify_intent("what is 9router")
    assert result.kind == "work"
    assert [s.department for s in result.steps] == ["research"]


def test_negation_returns_negated_kind_with_no_steps(monkeypatch):
    monkeypatch.setattr("backend.core.llm_client.get_or_client", lambda *_a, **_k: _fake_client(
        "don't build a website yet, just tell me what you found :: NEGATED"
    ))
    result = classify_intent("don't build a website yet, just tell me what you found")
    assert result.kind == "negated"
    assert result.steps == []


def test_compound_message_splits_into_ordered_department_steps(monkeypatch):
    monkeypatch.setattr("backend.core.llm_client.get_or_client", lambda *_a, **_k: _fake_client(
        "what is Blackstone the company and how do they make money :: research\n"
        "create a site to display the results of the research :: product_technical"
    ))
    result = classify_intent("what is Blackstone the company and how do they make money "
                              "then create a site to display the results of the research")
    assert result.kind == "work"
    assert [s.department for s in result.steps] == ["research", "product_technical"]


def test_chitchat_and_answer_kinds(monkeypatch):
    monkeypatch.setattr("backend.core.llm_client.get_or_client", lambda *_a, **_k: _fake_client("hey :: chitchat"))
    assert classify_intent("hey").kind == "chitchat"

    monkeypatch.setattr("backend.core.llm_client.get_or_client", lambda *_a, **_k: _fake_client("what were the results :: answer"))
    assert classify_intent("what were the results").kind == "answer"


def test_truncated_response_escalates_budget_and_retries(monkeypatch):
    calls = []

    class _FlakyClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            calls.append(kwargs["max_tokens"])
            if len(calls) == 1:
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="length")])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="research this :: research"), finish_reason="stop")])
    monkeypatch.setattr("backend.core.llm_client.get_or_client", lambda *_a, **_k: _FlakyClient())

    result = classify_intent("research this")
    assert result.kind == "work"
    assert calls[1] > calls[0]  # escalated on the retry


def test_total_failure_falls_back_to_a_single_unclassified_step(monkeypatch):
    def _raise(*_a, **_k):
        raise RuntimeError("provider down")
    monkeypatch.setattr("backend.core.llm_client.get_or_client", _raise)

    result = classify_intent("research this")
    assert result.kind == "work"
    assert result.steps == [type(result.steps[0])(text="research this", department="")]


def test_work_request_builds_a_dispatch_compatible_dict():
    from backend.tools.intent_classifier import IntentClassification, IntentStep

    classification = IntentClassification(kind="work", steps=[
        IntentStep(text="research Apple", department="research"),
        IntentStep(text="build a website about it", department="product_technical"),
    ])
    request = classification.work_request("research Apple then build a website about it")

    assert request["primary_capability"] == "research"
    assert set(request["required_capabilities"]) == {"research", "website"}
    assert request["requires_clarification"] is False
    assert request["deliverables"] == ["research Apple", "build a website about it"]
