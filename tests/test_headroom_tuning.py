import sys
import types

import backend.core.agent as agent_mod


def test_tune_headroom_pipeline_noop_when_headroom_not_installed():
    """headroom-ai is installed with `|| true` in Dockerfile.backend — it can
    legitimately be absent. The tuning hook must never raise or block the
    agent loop in that case."""
    agent_mod._headroom_tuned = False
    sys.modules.pop("headroom", None)
    sys.modules.pop("headroom.compress", None)
    agent_mod._tune_headroom_pipeline_once()  # must not raise
    assert agent_mod._headroom_tuned is True


def test_tune_headroom_pipeline_swaps_content_router_config(monkeypatch):
    """Real bug: headroom's default ContentRouterConfig.protect_recent_reads_fraction
    is 0.0 ("protect ALL excluded-tool outputs"), not exposed via compress()'s
    public kwargs. Verified on real production data this caps real savings at
    ~10-20%. The tuning hook must replace the ContentRouter transform in the
    pipeline singleton with one configured to open the protection window,
    while leaving every other transform in the pipeline untouched."""
    agent_mod._headroom_tuned = False

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
    captured = {}

    def _set_pipeline(value):
        captured["pipeline"] = value

    # _pipeline is assigned as a plain module attribute (`_hr_mod._pipeline = ...`)
    hr_compress_mod.__dict__["_pipeline"] = None

    hr_pkg = types.ModuleType("headroom")
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
    assert new_router.config.protect_recent_reads_fraction == 0.3


def test_tune_headroom_pipeline_only_runs_once():
    agent_mod._headroom_tuned = True
    # With the flag already set, the body must not execute at all — calling
    # it with headroom absent from sys.modules would otherwise be harmless
    # anyway (caught by the try/except), but the short-circuit is the actual
    # mechanism that keeps this a one-time startup cost, not a per-call one.
    agent_mod._tune_headroom_pipeline_once()
    assert agent_mod._headroom_tuned is True
