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


def test_malformed_merged_response_with_dangling_quote_is_rejected_and_retried(monkeypatch):
    """Confirmed live: for "what is the difference between blackstone and
    blackrock and create a website highlighting the differences" (a message
    that should split into a research step + a product_technical step,
    exactly like the other validated compound-message tests), one call
    instead merged both asks into a single, stopword-mangled line ending in
    a stray unbalanced quote: "is difference between blackstone blackrock
    create website highlighting differences'" -- dropping the website
    capability entirely and producing a garbled task title downstream. A
    dangling quote is never legitimate output and must be rejected/retried."""
    calls = []

    class _MangledThenCleanClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                content = "is difference between blackstone blackrock create website highlighting differences' :: research"
            else:
                content = ("what is the difference between blackstone and blackrock :: research\n"
                           "create a website highlighting the differences :: product_technical")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")])
    monkeypatch.setattr("backend.core.llm_client.get_or_client", lambda *_a, **_k: _MangledThenCleanClient())

    result = classify_intent("what is the difference between blackstone and blackrock and create a website highlighting the differences")

    assert len(calls) == 2  # the malformed first attempt was rejected and retried
    assert result.kind == "work"
    assert [s.department for s in result.steps] == ["research", "product_technical"]


def test_merged_research_response_is_repaired_when_website_clause_is_explicit(monkeypatch):
    """If the provider keeps only a research line but the founder explicitly
    asked to create/build a website, preserve the Product Delivery step."""
    monkeypatch.setattr("backend.core.llm_client.get_or_client", lambda *_a, **_k: _fake_client(
        "what is the difference between blackstone and blackrock and create a website highlighting the differences :: research"
    ))

    result = classify_intent("what is the difference between blackstone and blackrock and create a website highlighting the differences")

    assert result.kind == "work"
    assert [s.department for s in result.steps] == ["research", "product_technical"]
    assert "website" in result.steps[1].text.lower()


def test_hallucinated_echo_of_an_unrelated_example_is_rejected_and_retried(monkeypatch):
    """Confirmed live: for "what is the difference between blackrock and
    blackstone" (and, separately, the exact phrase "what is Blackstone the
    company and how do they make money" -- a phrase that classified
    correctly during validation), the model returned text lifted verbatim
    from an unrelated few-shot example in the prompt (a different one on
    different runs) labeled NEGATED, silently blocking real work with no
    error. A hallucinated line must be rejected (near-zero overlap with the
    real message) and the call retried rather than trusted."""
    calls = []

    class _HallucinatingThenCorrectClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                content = "don't build website yet, just tell me found :: NEGATED"
            else:
                content = "what is the difference between blackrock and blackstone :: research"
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")])
    monkeypatch.setattr("backend.core.llm_client.get_or_client", lambda *_a, **_k: _HallucinatingThenCorrectClient())

    result = classify_intent("what is the difference between blackrock and blackstone")

    assert len(calls) == 2  # the hallucinated first attempt was rejected and retried
    assert result.kind == "work"
    assert [s.department for s in result.steps] == ["research"]


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
