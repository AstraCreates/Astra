import os
import tempfile

# ── Test data isolation ──────────────────────────────────────────────────────
# Every on-disk store (company goals, sessions, credits, skills, copilot, brain
# records) is rooted at OBSIDIAN_VAULT. Point it at a throwaway dir BEFORE any
# backend module imports, so the test suite NEVER reads or mutates production
# data. (Running the suite against the live volume previously wiped a founder's
# goals/sessions and littered test-founder files.)
_TEST_VAULT = os.environ.get("ASTRA_TEST_VAULT") or tempfile.mkdtemp(prefix="astra_test_vault_")
os.environ["OBSIDIAN_VAULT"] = _TEST_VAULT

import pytest
import fakeredis.aioredis


@pytest.fixture(autouse=True)
def _isolate_vault():
    """Belt-and-suspenders: keep OBSIDIAN_VAULT pinned to the throwaway dir for
    every test, even if something reset it."""
    os.environ["OBSIDIAN_VAULT"] = _TEST_VAULT
    yield


@pytest.fixture(autouse=False)
def fake_redis(mocker):
    fake = fakeredis.aioredis.FakeRedis()
    mocker.patch("backend.bus.redis_bus.RedisBus._get_redis", return_value=fake)
    return fake
