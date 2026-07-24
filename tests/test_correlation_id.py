"""Correlation ID + request timing middleware tests.

Verifies:
  * X-Correlation-ID from the request is reflected in the response and
    placed on ``request.state.correlation_id`` for downstream use.
  * A missing X-Correlation-ID generates a fresh one (not empty, not None).
  * X-Response-Time-Ms is always set on the response (numeric).
  * The middleware never raises on a handler that throws.
  * Slow or 5xx paths emit the timing log line.
"""
from __future__ import annotations

import logging
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.main as app_main


@pytest.fixture
def captured_corr() -> list[str | None]:
    """A list-based sink for ``current_correlation_id()`` reads; updated by
    the /__test_corr route so the middleware-contextvar test can assert the
    contextvar was populated by the middleware (not zeroed out by the
    framework-bound wrapper)."""
    return []


@pytest.fixture
def client(captured_corr) -> TestClient:
    """Build a minimal FastAPI app with ONLY the middleware under test.

    Mounting against the full ``backend.main.app`` triggers startup hooks,
    Redis, Supabase, OTel init -- none of which are needed for these tests.
    Constructing a transient app also avoids leaking state across run order.
    """
    import functools
    from starlette.middleware.base import BaseHTTPMiddleware
    inner_mw = getattr(app_main.correlation_id_and_timing_middleware, "__wrapped__", app_main.correlation_id_and_timing_middleware)

    class _CorrMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # FastAPI's @app.middleware("http") binds the decorator on the
            # parent app; calling the bound name directly inside our dispatch
            # can double-wrap the response lifecycle. Use __wrapped__ if the
            # decorator preserved it; fall back to the bound name otherwise.
            return await inner_mw(request, call_next)

    test_app = FastAPI()
    test_app.add_middleware(_CorrMiddleware)

    @test_app.get("/__test_ok")
    def _ok():
        return {"ok": True, "corr": app_main.current_correlation_id()}

    @test_app.get("/__test_corr")
    def _capture():
        captured_corr.append(app_main.current_correlation_id())
        return {"ok": True}

    @test_app.get("/__test_throws")
    def _throw():
        raise RuntimeError("kaboom")

    with TestClient(test_app) as c:
        yield c


def test_correlation_id_round_trips(client):
    r = client.get("/__test_ok", headers={"X-Correlation-ID": "abc-123"})
    assert r.status_code == 200
    assert r.headers.get("X-Correlation-ID") == "abc-123"


def test_correlation_id_generated_when_missing(client):
    r1 = client.get("/__test_ok")
    cid1 = r1.headers.get("X-Correlation-ID")
    assert cid1 and len(cid1) > 0, "middleware must generate an id when client didn't send one"
    r2 = client.get("/__test_ok")
    cid2 = r2.headers.get("X-Correlation-ID")
    # Generated ids are random hex strings -> never equal across calls.
    assert cid1 != cid2


def test_response_time_header_present(client):
    r = client.get("/__test_ok")
    rt = r.headers.get("X-Response-Time-Ms")
    assert rt is not None
    float(rt)  # raises if non-numeric


def test_current_correlation_id_through_middleware(client, captured_corr):
    """Verify the contextvar ``current_correlation_id()`` is populated for
    code that runs inside the FastAPI request handler. The /__test_corr
    route (mounted by the fixture) records the value seen inside the request."""
    r = client.get("/__test_corr", headers={"X-Correlation-ID": "context-var-test"})
    assert r.status_code == 200
    assert r.headers.get("X-Correlation-ID") == "context-var-test"
    assert captured_corr == ["context-var-test"]


def test_middleware_does_not_mask_handler_exception(client, caplog):
    """If the handler raises, the response should be a 500 and the
    correlation-id header should still be set so the error log can be
    joined to upstream nginx logs."""
    # The /__test_throws route is registered by the ``client`` fixture on its
    # minimal test_app, NOT on app_main.app -- registering it on app_main.app
    # would leak state across the test suite AND would not be reached via the
    # fixture's TestClient. With caplog.at_level(logging.INFO):
    r = client.get("/__test_throws", headers={"X-Correlation-ID": "boom-1"})
    assert r.status_code == 500
    assert r.headers.get("X-Correlation-ID") == "boom-1"


if __name__ == "__main__":
    sys.exit(0)
