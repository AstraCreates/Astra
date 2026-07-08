from pathlib import Path

from backend.production_env import (
    AUTH_SOURCE_ENV,
    REQUIRED_PRODUCTION_ENV,
    audit_env_file,
    audit_runtime_settings,
    render_missing_env_template,
)


_RUNTIME_FIELDS = [
    "backend_url", "frontend_url", "astra_require_auth", "astra_platform_admins",
    "astra_cors_origins", "astra_creds_key", "astra_alert_webhook_url",
    "stripe_secret_key", "stripe_webhook_secret", "stripe_price_starter",
    "stripe_price_team", "stripe_price_scale", "github_token", "vercel_token",
    "agent_model_api_key", "planner_model_api_key", "chat_model_api_key",
    "nextauth_secret", "searxng_secret_key", "wm_db_password",
    "astra_jwt_jwks_url", "astra_jwt_secret", "astra_trust_auth_headers",
]


class _FakeSettings:
    model_fields = {name: None for name in _RUNTIME_FIELDS}

    def __init__(self, **overrides):
        for name in _RUNTIME_FIELDS:
            setattr(self, name, overrides.get(name, ""))


def test_production_env_audit_reports_status_without_values(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "BACKEND_URL=https://api.astracreates.com",
                "FRONTEND_URL=https://astracreates.com",
                "ASTRA_REQUIRE_AUTH=true",
                "ASTRA_PLATFORM_ADMINS=admin_secret_user",
                "ASTRA_JWT_SECRET=super_secret_jwt",
                "ASTRA_CREDS_KEY=very_secret_creds",
                "STRIPE_SECRET_KEY=sk_live_secret",
            ]
        )
    )

    result = audit_env_file(env_file)
    rendered = str(result)

    assert result["env_file_exists"] is True
    assert "ASTRA_ALERT_WEBHOOK_URL" in result["missing"]
    assert result["auth_source_configured"] is True
    assert "admin_secret_user" not in rendered
    assert "super_secret_jwt" not in rendered
    assert "very_secret_creds" not in rendered
    assert "sk_live_secret" not in rendered


def test_production_env_template_only_outputs_missing_keys(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "BACKEND_URL=https://api.astracreates.com",
                "ASTRA_CREDS_KEY=do_not_print",
                "ASTRA_TRUST_AUTH_HEADERS=true",
            ]
        )
    )

    template = render_missing_env_template(env_file)

    assert "BACKEND_URL=" not in template
    assert "ASTRA_CREDS_KEY=" not in template
    assert "do_not_print" not in template
    assert "FRONTEND_URL=https://astracreates.com" in template
    assert "ASTRA_JWT_SECRET=" not in template
    assert "# Set one auth source:" not in template


def test_production_env_accepts_any_auth_source(tmp_path: Path):
    for key, value in [
        ("ASTRA_JWT_JWKS_URL", "https://issuer.example/.well-known/jwks.json"),
        ("ASTRA_JWT_SECRET", "secret"),
        ("ASTRA_TRUST_AUTH_HEADERS", "true"),
    ]:
        env_file = tmp_path / f"{key}.env"
        body = [f"{env_key}=configured" for env_key in REQUIRED_PRODUCTION_ENV]
        body.extend(f"{env_key}=" for env_key in AUTH_SOURCE_ENV)
        body.append(f"{key}={value}")
        env_file.write_text("\n".join(body))

        result = audit_env_file(env_file)

        assert result["auth_source_configured"] is True
        assert result["ok"] is True


def test_production_env_missing_file_is_safe(tmp_path: Path):
    missing_file = tmp_path / "missing.env"

    result = audit_env_file(missing_file)
    template = render_missing_env_template(missing_file)

    assert result["ok"] is False
    assert result["env_file_exists"] is False
    assert set(result["missing"]) == set(REQUIRED_PRODUCTION_ENV)
    assert "ASTRA_JWT_SECRET=" in template
    assert "STRIPE_SECRET_KEY=" in template


def test_audit_runtime_settings_does_not_misclassify_non_localhost_staging_as_production():
    """Real incident: a nip.io-hosted staging box (real public IP, not literal
    'localhost', but ASTRA_REQUIRE_AUTH=false — never configured with Stripe/
    NextAuth secrets) got classified as "production" by hostname string-matching
    alone and hard-crashed the whole backend on boot demanding those secrets."""
    settings = _FakeSettings(
        backend_url="http://178.105.231.73.nip.io",
        frontend_url="http://178.105.231.73.nip.io",
        astra_require_auth="false",
        astra_creds_key="realkey",
        astra_cors_origins="*",
        github_token="realtoken",
        vercel_token="realtoken",
        agent_model_api_key="realkey",
        planner_model_api_key="realkey",
        chat_model_api_key="realkey",
        searxng_secret_key="realkey",
        wm_db_password="realkey",
        astra_trust_auth_headers="false",
    )

    result = audit_runtime_settings(settings)

    assert result["mode"] == "local"
    assert result["ok"] is True


def test_audit_runtime_settings_still_fails_real_production_misconfiguration():
    """The fix above must not blanket-disable the check — a real production
    deploy (ASTRA_REQUIRE_AUTH=true, real domain) missing Stripe keys must
    still fail loudly."""
    settings = _FakeSettings(
        backend_url="https://api.astracreates.com",
        frontend_url="https://astracreates.com",
        astra_require_auth="true",
        astra_platform_admins="founder@astracreates.com",
        astra_cors_origins="https://astracreates.com",
        astra_creds_key="realkey",
        astra_alert_webhook_url="https://hooks.example.com/x",
        github_token="realtoken",
        vercel_token="realtoken",
        agent_model_api_key="realkey",
        planner_model_api_key="realkey",
        chat_model_api_key="realkey",
        nextauth_secret="realsecret",
        searxng_secret_key="realkey",
        wm_db_password="realkey",
        astra_jwt_secret="realjwtsecret",
        astra_trust_auth_headers="false",
        # stripe_* left blank on purpose
    )

    result = audit_runtime_settings(settings)

    assert result["mode"] == "production"
    assert result["ok"] is False
    assert any("STRIPE" in err for err in result["errors"])
