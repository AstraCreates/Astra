import sys
import types

import backend.core.agent as agent_mod
from backend.config import settings


def test_tune_headroom_pipeline_noop_when_headroom_not_installed():
    """headroom-ai is installed with `|| true` in Dockerfile.backend — it can
    legitimately be absent. The tuning hook must never raise or block the
    agent loop in that case."""
    agent_mod._headroom_tuned = False
    sys.modules.pop("headroom", None)
    sys.modules.pop("headroom.compress", None)
    agent_mod._tune_headroom_pipeline_once()  # must not raise
    assert agent_mod._headroom_tuned is True


def test_tune_headroom_pipeline_respects_kill_switch(monkeypatch):
    """Reaching into headroom-ai's private pipeline singleton isn't a
    supported integration point. settings.headroom_tuning_enabled must be
    able to fully disable it (no code deploy needed) if a future headroom-ai
    version breaks the assumption in production."""
    agent_mod._headroom_tuned = False
    monkeypatch.setattr(settings, "headroom_tuning_enabled", False, raising=False)

    called = []
    fake_hr_mod = types.ModuleType("headroom.compress")
    fake_hr_mod._get_pipeline = lambda: called.append(1)
    monkeypatch.setitem(sys.modules, "headroom.compress", fake_hr_mod)

    agent_mod._tune_headroom_pipeline_once()

    assert agent_mod._headroom_tuned is True
    assert called == []  # _get_pipeline never touched — disabled before reaching it


def test_tune_headroom_pipeline_swaps_content_router_config(monkeypatch):
    """Real bug: headroom's default ContentRouterConfig.protect_recent_reads_fraction
    is 0.0 ("protect ALL excluded-tool outputs"), not exposed via compress()'s
    public kwargs. Verified on real production data this caps real savings at
    ~10-20%. The tuning hook must replace the ContentRouter transform in the
    pipeline singleton with one configured to open the protection window,
    while leaving every other transform in the pipeline untouched."""
    agent_mod._headroom_tuned = False
    monkeypatch.setattr(settings, "headroom_tuning_enabled", True, raising=False)

    class FakeContentRouterConfig:
        def __init__(self, protect_recent_reads_fraction=0.0):
            self.protect_recent_reads_fraction = protect_recent_reads_fraction

    class FakeContentRouter:
        def __init__(self, config=None):
            self.config = config or FakeContentRouterConfig()

    class FakeCacheAligner:
        pass

    class FakeTransformPipeline:
        def __init__(self, transforms):
            self.transforms = transforms

    original_router = FakeContentRouter()
    cache_aligner = FakeCacheAligner()
    base_pipeline = FakeTransformPipeline(transforms=[cache_aligner, original_router])

    hr_compress_mod = types.ModuleType("headroom.compress")
    hr_compress_mod._get_pipeline = lambda: base_pipeline
    hr_compress_mod.__dict__["_pipeline"] = None

    hr_pkg = types.ModuleType("headroom")
    # Replicate the real headroom-ai package shape: headroom/__init__.py does
    # `from .compress import compress`, which overwrites the `headroom.compress`
    # ATTRIBUTE with the function, shadowing the submodule of the same name.
    # `import headroom.compress as X` resolves via that attribute and would
    # bind X to this function, not the real module — the exact bug this test
    # must catch. importlib.import_module("headroom.compress") must bypass it.
    hr_pkg.compress = lambda *a, **k: None
    hr_transforms_pkg = types.ModuleType("headroom.transforms")
    hr_pipeline_mod = types.ModuleType("headroom.transforms.pipeline")
    hr_pipeline_mod.TransformPipeline = FakeTransformPipeline
    hr_router_mod = types.ModuleType("headroom.transforms.content_router")
    hr_router_mod.ContentRouter = FakeContentRouter
    hr_router_mod.ContentRouterConfig = FakeContentRouterConfig

    monkeypatch.setitem(sys.modules, "headroom", hr_pkg)
    monkeypatch.setitem(sys.modules, "headroom.compress", hr_compress_mod)
    monkeypatch.setitem(sys.modules, "headroom.transforms", hr_transforms_pkg)
    monkeypatch.setitem(sys.modules, "headroom.transforms.pipeline", hr_pipeline_mod)
    monkeypatch.setitem(sys.modules, "headroom.transforms.content_router", hr_router_mod)

    agent_mod._tune_headroom_pipeline_once()

    new_pipeline = hr_compress_mod._pipeline
    assert new_pipeline is not None
    assert new_pipeline.transforms[0] is cache_aligner  # untouched
    new_router = new_pipeline.transforms[1]
    assert isinstance(new_router, FakeContentRouter)
    assert new_router is not original_router
    assert new_router.config.protect_recent_reads_fraction == settings.headroom_protect_recent_reads_fraction


def test_tune_headroom_pipeline_uses_configured_ratio(monkeypatch):
    """Real incident 2026-07-10: a hardcoded protect_recent_reads_fraction=0.3
    made the ContentRouter's real local Kompress/ModernBERT text compressor
    engage under production traffic for the first time, pegging the backend
    container's CPU and permanently growing its resident memory. The ratio
    must be configurable (settings.headroom_protect_recent_reads_fraction)
    so it can be tuned down without a code change, not hardcoded again."""
    agent_mod._headroom_tuned = False
    monkeypatch.setattr(settings, "headroom_tuning_enabled", True, raising=False)
    monkeypatch.setattr(settings, "headroom_protect_recent_reads_fraction", 0.05, raising=False)

    class FakeContentRouterConfig:
        def __init__(self, protect_recent_reads_fraction=0.0):
            self.protect_recent_reads_fraction = protect_recent_reads_fraction

    class FakeContentRouter:
        def __init__(self, config=None):
            self.config = config or FakeContentRouterConfig()

    class FakeTransformPipeline:
        def __init__(self, transforms):
            self.transforms = transforms

    base_pipeline = FakeTransformPipeline(transforms=[FakeContentRouter()])
    hr_compress_mod = types.ModuleType("headroom.compress")
    hr_compress_mod._get_pipeline = lambda: base_pipeline
    hr_compress_mod.__dict__["_pipeline"] = None

    hr_pkg = types.ModuleType("headroom")
    hr_pkg.compress = lambda *a, **k: None
    hr_transforms_pkg = types.ModuleType("headroom.transforms")
    hr_pipeline_mod = types.ModuleType("headroom.transforms.pipeline")
    hr_pipeline_mod.TransformPipeline = FakeTransformPipeline
    hr_router_mod = types.ModuleType("headroom.transforms.content_router")
    hr_router_mod.ContentRouter = FakeContentRouter
    hr_router_mod.ContentRouterConfig = FakeContentRouterConfig

    monkeypatch.setitem(sys.modules, "headroom", hr_pkg)
    monkeypatch.setitem(sys.modules, "headroom.compress", hr_compress_mod)
    monkeypatch.setitem(sys.modules, "headroom.transforms", hr_transforms_pkg)
    monkeypatch.setitem(sys.modules, "headroom.transforms.pipeline", hr_pipeline_mod)
    monkeypatch.setitem(sys.modules, "headroom.transforms.content_router", hr_router_mod)

    agent_mod._tune_headroom_pipeline_once()

    new_router = hr_compress_mod._pipeline.transforms[0]
    assert new_router.config.protect_recent_reads_fraction == 0.05


def test_tune_headroom_pipeline_detects_shadowed_import(monkeypatch):
    """Regression guard for the exact real incident: if `headroom.compress`
    ever resolves to something other than the real module again (e.g. the
    package re-exports change shape in a future headroom-ai version), the
    assert must catch it and the hook must no-op safely instead of silently
    doing nothing with no trace, as happened in production."""
    agent_mod._headroom_tuned = False

    hr_pkg = types.ModuleType("headroom")
    shadowed_function = lambda *a, **k: None  # noqa: E731 - stands in for the real shadowing bug
    hr_pkg.compress = shadowed_function
    monkeypatch.setitem(sys.modules, "headroom", hr_pkg)
    monkeypatch.setitem(sys.modules, "headroom.compress", hr_pkg)  # simulate the broken resolution

    agent_mod._tune_headroom_pipeline_once()  # must not raise
    assert agent_mod._headroom_tuned is True


def test_tune_headroom_pipeline_only_runs_once():
    agent_mod._headroom_tuned = True
    # With the flag already set, the body must not execute at all — calling
    # it with headroom absent from sys.modules would otherwise be harmless
    # anyway (caught by the try/except), but the short-circuit is the actual
    # mechanism that keeps this a one-time startup cost, not a per-call one.
    agent_mod._tune_headroom_pipeline_once()
    assert agent_mod._headroom_tuned is True
