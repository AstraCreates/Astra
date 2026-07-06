from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api.credits_routes import credits_router
from backend.api.dashboard_routes import router as dashboard_router
from backend.api.library_routes import library_router
from backend.api.skills_routes import skills_router
from backend.config import settings


def _client(router) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize(
    ("router", "path"),
    [
        (credits_router, "/credits?founder_id=founder-auth"),
        (library_router, "/library?founder_id=founder-auth"),
        (skills_router, "/skills?founder_id=founder-auth"),
        (dashboard_router, "/dashboard/founder-auth"),
    ],
)
def test_founder_scoped_routes_require_auth_in_strict_mode(monkeypatch, router, path):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", False)
    monkeypatch.setattr(settings, "astra_allow_dev_auth", False)

    response = _client(router).get(path)

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def test_credits_route_allows_local_dev_founder_dependency(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr("backend.credits.store.get_credits", lambda founder_id: {
        "founder_id": founder_id,
        "balance": 7,
        "total_granted": 9,
        "total_purchased": 0,
        "total_used": 2,
        "transactions": [{"type": "grant"}],
    })
    monkeypatch.setattr("backend.credits.gold_price.get_gold_price", lambda: 2.5)

    response = _client(credits_router).get("/credits?founder_id=founder-dev")

    assert response.status_code == 200
    assert response.json()["founder_id"] == "founder-dev"


def test_library_route_allows_local_dev_founder_dependency(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(
        "backend.api.library_routes.list_files",
        lambda founder_id, department=None: [{"id": "file_1", "founder_id": founder_id, "department": department}],
    )

    response = _client(library_router).get("/library?founder_id=founder-dev&department=legal")

    assert response.status_code == 200
    assert response.json()["files"][0]["founder_id"] == "founder-dev"


def test_skills_route_allows_local_dev_founder_dependency(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(
        "backend.api.skills_routes.list_skills",
        lambda founder_id: [{"id": "skill_1", "founder_id": founder_id, "name": "Research"}],
    )

    response = _client(skills_router).get("/skills?founder_id=founder-dev")

    assert response.status_code == 200
    assert response.json()["founder_id"] == "founder-dev"


def test_dashboard_route_allows_local_dev_current_founder_helper(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(
        "backend.api.dashboard_routes.dashboard_get",
        lambda founder_id: {"founder_id": founder_id, "elements": []},
    )

    response = _client(dashboard_router).get("/dashboard/founder-dev")

    assert response.status_code == 200
    assert response.json()["founder_id"] == "founder-dev"


@pytest.mark.parametrize(
    ("router", "path", "body"),
    [
        (credits_router, "/credits/deduct", {"founder_id": "founder-auth", "amount": 1, "description": "x"}),
        (credits_router, "/credits/checkout", {"founder_id": "founder-auth", "pack": "starter"}),
        (library_router, "/library", {"founder_id": "founder-auth", "department": "legal", "filename": "nda.md", "content": "body"}),
        (skills_router, "/skills", {"founder_id": "founder-auth", "name": "Research", "description": "", "content": ""}),
    ],
)
def test_founder_body_routes_require_auth_in_strict_mode(monkeypatch, router, path, body):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", False)
    monkeypatch.setattr(settings, "astra_allow_dev_auth", False)

    response = _client(router).post(path, json=body)

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def test_credits_checkout_allows_local_dev_founder_dependency(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", False)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_123")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example")

    class _FakeSession:
        url = "https://checkout.stripe.test/session_123"

    class _FakeStripe:
        api_key = ""

        class checkout:
            class Session:
                @staticmethod
                def create(**kwargs):
                    return _FakeSession()

    monkeypatch.setitem(__import__("sys").modules, "stripe", _FakeStripe)

    response = _client(credits_router).post(
        "/credits/checkout",
        json={"founder_id": "founder-dev", "pack": "starter"},
    )

    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://checkout.stripe.test/session_123"
