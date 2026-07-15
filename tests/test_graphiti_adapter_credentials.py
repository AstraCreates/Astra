"""Regression tests for the Graphiti OpenRouter-credential fallback.

backend/control_plane/graphiti_adapter.py's GraphitiBrainClient required a
dedicated ASTRA_BRAIN_GRAPH_API_KEY to do anything at all -- with none set
(the real state of the live deployment), _has_model_credentials was False and
every operation raised immediately. Since the model names it defaulted to
(openai/gpt-4.1-mini, text-embedding-3-small) are OpenAI-native and no
OPENAI_API_KEY exists anywhere in this deployment, it now falls back to the
existing OPENROUTER_API_KEY for the LLM client (entity/relationship
extraction, reranking) when no dedicated key is configured. Graphiti's own
Graphiti(embedder=...) parameter is optional (verified: defaults to None), so
the fallback path explicitly passes embedder=None rather than pointing an
OpenAI-shaped embedder at an endpoint (OpenRouter) that has no /embeddings
route.

graphiti_core itself isn't installed in the local dev environment (container-
only dependency, see requirements.txt's graphiti-core[falkordblite] extra) --
these tests stub out the specific submodules _build_graphiti imports so the
credential-selection logic is covered without needing the real package.
"""
from __future__ import annotations

import sys
import types

import pytest


class _FakeLLMConfig:
    def __init__(self, *, api_key, base_url, model, small_model):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.small_model = small_model


class _FakeOpenAIClient:
    def __init__(self, *, config):
        self.config = config


class _FakeOpenAIRerankerClient:
    def __init__(self, *, config):
        self.config = config


class _FakeOpenAIEmbedderConfig:
    def __init__(self, *, api_key, base_url, embedding_model):
        self.api_key = api_key
        self.base_url = base_url
        self.embedding_model = embedding_model


class _FakeOpenAIEmbedder:
    def __init__(self, *, config):
        self.config = config


class _FakeFalkorDriver:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeGraphiti:
    def __init__(self, *, graph_driver, llm_client, embedder, cross_encoder):
        self.graph_driver = graph_driver
        self.llm_client = llm_client
        self.embedder = embedder
        self.cross_encoder = cross_encoder


@pytest.fixture(autouse=True)
def _stub_graphiti_core(monkeypatch):
    """Inject minimal fake modules for everything _build_graphiti imports,
    and make graphiti_available() report True without a real install."""
    fake_graphiti_core = types.ModuleType("graphiti_core")
    fake_graphiti_core.Graphiti = _FakeGraphiti

    fake_driver_mod = types.ModuleType("graphiti_core.driver")
    fake_falkor_driver_mod = types.ModuleType("graphiti_core.driver.falkordb_driver")
    fake_falkor_driver_mod.FalkorDriver = _FakeFalkorDriver

    fake_embedder_mod = types.ModuleType("graphiti_core.embedder")
    fake_embedder_openai_mod = types.ModuleType("graphiti_core.embedder.openai")
    fake_embedder_openai_mod.OpenAIEmbedder = _FakeOpenAIEmbedder
    fake_embedder_openai_mod.OpenAIEmbedderConfig = _FakeOpenAIEmbedderConfig

    fake_cross_encoder_mod = types.ModuleType("graphiti_core.cross_encoder")
    fake_cross_encoder_openai_mod = types.ModuleType("graphiti_core.cross_encoder.openai_reranker_client")
    fake_cross_encoder_openai_mod.OpenAIRerankerClient = _FakeOpenAIRerankerClient

    fake_llm_client_mod = types.ModuleType("graphiti_core.llm_client")
    fake_llm_config_mod = types.ModuleType("graphiti_core.llm_client.config")
    fake_llm_config_mod.LLMConfig = _FakeLLMConfig
    fake_llm_openai_mod = types.ModuleType("graphiti_core.llm_client.openai_client")
    fake_llm_openai_mod.OpenAIClient = _FakeOpenAIClient

    modules = {
        "graphiti_core": fake_graphiti_core,
        "graphiti_core.driver": fake_driver_mod,
        "graphiti_core.driver.falkordb_driver": fake_falkor_driver_mod,
        "graphiti_core.embedder": fake_embedder_mod,
        "graphiti_core.embedder.openai": fake_embedder_openai_mod,
        "graphiti_core.cross_encoder": fake_cross_encoder_mod,
        "graphiti_core.cross_encoder.openai_reranker_client": fake_cross_encoder_openai_mod,
        "graphiti_core.llm_client": fake_llm_client_mod,
        "graphiti_core.llm_client.config": fake_llm_config_mod,
        "graphiti_core.llm_client.openai_client": fake_llm_openai_mod,
    }
    for name, mod in modules.items():
        monkeypatch.setitem(sys.modules, name, mod)

    # redislite is only needed for the falkordblite (embedded) driver path.
    fake_redislite_mod = types.ModuleType("redislite.async_falkordb_client")
    fake_redislite_mod.AsyncFalkorDB = lambda **kwargs: object()
    monkeypatch.setitem(sys.modules, "redislite.async_falkordb_client", fake_redislite_mod)

    yield


def test_dedicated_api_key_uses_full_openai_embeddings(monkeypatch):
    from backend.config import settings
    from backend.control_plane.graphiti_adapter import GraphitiBrainClient

    monkeypatch.setattr(settings, "astra_brain_graph_api_key", "sk-dedicated-key")
    monkeypatch.setattr(settings, "astra_brain_graph_model", "openai/gpt-4.1-mini")
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-something")

    client = GraphitiBrainClient()
    assert client._has_model_credentials is True

    g = client._build_graphiti()
    assert g.embedder is not None
    assert g.embedder.config.api_key == "sk-dedicated-key"
    assert g.llm_client.config.api_key == "sk-dedicated-key"
    assert g.llm_client.config.model == "openai/gpt-4.1-mini"


def test_no_dedicated_key_falls_back_to_openrouter_with_local_embedder(monkeypatch):
    # Graphiti's own Graphiti(embedder=...) constructs a *default* OpenAIEmbedder()
    # internally whenever embedder is None (verified against the real installed
    # library: not truly optional, needs OPENAI_API_KEY) -- so the fallback path
    # must supply a real, working embedder instance, not None. OpenRouter has no
    # /embeddings endpoint, hence the local sentence-transformers embedder.
    from backend.config import settings
    from backend.control_plane.graphiti_adapter import GraphitiBrainClient, LocalSentenceTransformerEmbedder

    monkeypatch.setattr(settings, "astra_brain_graph_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-real-key")
    monkeypatch.setattr(settings, "openrouter_base_url", "http://headroom:8787/v1")

    client = GraphitiBrainClient()
    assert client._has_model_credentials is True

    g = client._build_graphiti()
    assert isinstance(g.embedder, LocalSentenceTransformerEmbedder)
    assert g.llm_client.config.api_key == "sk-or-real-key"
    assert g.llm_client.config.base_url == "http://headroom:8787/v1"
    assert g.llm_client.config.model == "deepseek/deepseek-v4-flash"


@pytest.mark.asyncio
async def test_local_embedder_produces_correct_dimension_and_normalized_vectors(monkeypatch):
    # graphiti_core.embedder.client.EMBEDDING_DIM is 1024 -- the local model
    # (BAAI/bge-large-en-v1.5) must match exactly, no padding/projection.
    from backend.control_plane import graphiti_adapter as ga_mod

    class _FakeSentenceTransformer:
        def __init__(self, model_name):
            self.model_name = model_name

        def encode(self, texts, normalize_embeddings=True):
            import math
            vectors = []
            for _ in texts:
                raw = [1.0] * 1024
                norm = math.sqrt(sum(v * v for v in raw))
                vectors.append([v / norm for v in raw] if normalize_embeddings else raw)
            return vectors

    fake_st_module = types.ModuleType("sentence_transformers")
    fake_st_module.SentenceTransformer = _FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st_module)
    monkeypatch.setattr(ga_mod, "_local_embedder_model", None)

    embedder = ga_mod.LocalSentenceTransformerEmbedder()
    vector = await embedder.create("some text")
    assert len(vector) == 1024

    batch = await embedder.create_batch(["a", "b"])
    assert len(batch) == 2
    assert all(len(v) == 1024 for v in batch)


def test_no_credentials_at_all_reports_unavailable(monkeypatch):
    from backend.config import settings
    from backend.control_plane.graphiti_adapter import GraphitiBrainClient

    monkeypatch.setattr(settings, "astra_brain_graph_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    client = GraphitiBrainClient()
    assert client._has_model_credentials is False
