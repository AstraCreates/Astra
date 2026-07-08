"""Safe production .env auditing and missing-key template generation."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TRUE_VALUES = {"1", "true", "yes", "on"}

REQUIRED_PRODUCTION_ENV: tuple[str, ...] = (
    "BACKEND_URL",
    "FRONTEND_URL",
    "ASTRA_REQUIRE_AUTH",
    "ASTRA_PLATFORM_ADMINS",
    "ASTRA_CORS_ORIGINS",
    "ASTRA_CREDS_KEY",
    "ASTRA_ALERT_WEBHOOK_URL",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PRICE_STARTER",
    "STRIPE_PRICE_TEAM",
    "STRIPE_PRICE_SCALE",
    "GITHUB_TOKEN",
    "VERCEL_TOKEN",
    "AGENT_MODEL_API_KEY",
    "PLANNER_MODEL_API_KEY",
    "CHAT_MODEL_API_KEY",
    "NEXTAUTH_SECRET",
    "SEARXNG_SECRET_KEY",
    "WM_DB_PASSWORD",
)

AUTH_SOURCE_ENV: tuple[str, ...] = (
    "ASTRA_JWT_JWKS_URL",
    "ASTRA_JWT_SECRET",
    "ASTRA_TRUST_AUTH_HEADERS",
)

DEFAULT_PLACEHOLDERS: dict[str, str] = {
    "BACKEND_URL": "https://api.astracreates.com",
    "FRONTEND_URL": "https://astracreates.com",
    "ASTRA_REQUIRE_AUTH": "true",
}

PLACEHOLDER_EXACT = {
    "change-me",
    "placeholder",
    "none",
}

PLACEHOLDER_SUBSTRINGS = (
    "change-me",
    "placeholder",
    "example.com",
    "localhost",
    "127.0.0.1",
    "openss1-rand-hex",
    "openssl-rand-hex",
)


@dataclass(frozen=True)
class EnvValue:
    key: str
    configured: bool
    empty: bool


def parse_env_file(path: str | Path = ".env") -> dict[str, str]:
    """Parse a dotenv file without expanding values or exposing them in reports."""
    env_path = Path(path)
    if not env_path.exists():
        return {}

    parsed: dict[str, str] = {}
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            parsed[key] = value
    return parsed


def audit_env_file(path: str | Path = ".env") -> dict[str, Any]:
    """Return a production env audit that only reports keys and status, never values."""
    env_path = Path(path)
    values = parse_env_file(env_path)
    required = [_env_status(key, values) for key in REQUIRED_PRODUCTION_ENV]
    missing = [item.key for item in required if not item.configured]
    placeholders = [key for key, value in values.items() if _looks_placeholder(key, value)]
    auth = [_env_status(key, values) for key in AUTH_SOURCE_ENV]
    auth_source_configured = _auth_source_configured(values)

    return {
        "ok": env_path.exists() and not missing and auth_source_configured and not placeholders,
        "env_file": str(env_path),
        "env_file_exists": env_path.exists(),
        "required": [item.__dict__ for item in required],
        "missing": missing,
        "missing_count": len(missing),
        "placeholder_values": sorted(placeholders),
        "auth_sources": [item.__dict__ for item in auth],
        "auth_source_configured": auth_source_configured,
        "auth_source_requirement": "Set ASTRA_JWT_JWKS_URL or ASTRA_JWT_SECRET, or ASTRA_TRUST_AUTH_HEADERS=true.",
        "summary": _summary(env_path.exists(), missing, auth_source_configured, placeholders),
    }


def render_missing_env_template(path: str | Path = ".env") -> str:
    """Render only missing keys as KEY= placeholders."""
    values = parse_env_file(path)
    lines: list[str] = []
    for key in REQUIRED_PRODUCTION_ENV:
        if not _configured(values.get(key, "")):
            lines.append(f"{key}={DEFAULT_PLACEHOLDERS.get(key, '')}")

    if not _auth_source_configured(values):
        lines.extend(
            [
                "# Set one auth source:",
                "ASTRA_JWT_SECRET=",
                "# or ASTRA_JWT_JWKS_URL=",
                "# or ASTRA_TRUST_AUTH_HEADERS=true",
            ]
        )
    return "\n".join(lines) + ("\n" if lines else "")


def _env_status(key: str, values: dict[str, str]) -> EnvValue:
    value = values.get(key, "")
    return EnvValue(key=key, configured=_configured(value), empty=key in values and not _configured(value))


def _configured(value: str) -> bool:
    return bool(str(value).strip())


def _looks_placeholder(key: str, value: str) -> bool:
    normalized = str(value or "").strip().strip("\"'")
    if not normalized:
        return False
    lower = normalized.lower()
    if lower in PLACEHOLDER_EXACT:
        return True
    if any(token in lower for token in PLACEHOLDER_SUBSTRINGS):
        if key in {"BACKEND_URL", "FRONTEND_URL"} and lower.startswith("http://localhost"):
            return True
        if key.endswith("_SECRET") or key.endswith("_KEY") or "PASSWORD" in key or "TOKEN" in key:
            return True
    if key == "ASTRA_CORS_ORIGINS" and "*" in normalized:
        return True
    return False


def _auth_source_configured(values: dict[str, str]) -> bool:
    if _configured(str(values.get("ASTRA_JWT_JWKS_URL", "") or "")):
        return True
    if _configured(str(values.get("ASTRA_JWT_SECRET", "") or "")):
        return True
    return str(values.get("ASTRA_TRUST_AUTH_HEADERS", "") or "").strip().lower() in TRUE_VALUES


def _summary(env_exists: bool, missing: list[str], auth_source_configured: bool, placeholders: list[str]) -> str:
    if not env_exists:
        return ".env file is missing."
    if missing or not auth_source_configured or placeholders:
        count = len(missing) + len(placeholders) + (0 if auth_source_configured else 1)
        return f"Production env is missing {count} required item(s)."
    return "Production env required keys are configured."


def audit_runtime_settings(settings: Any) -> dict[str, Any]:
    """Validate the active runtime settings object for production safety."""
    values = {
        key.upper(): getattr(settings, key, "")
        for key in getattr(type(settings), "model_fields", {})
    }
    required = [_env_status(key, values) for key in REQUIRED_PRODUCTION_ENV]
    missing = [item.key for item in required if not item.configured]
    placeholders = [key for key, value in values.items() if _looks_placeholder(key, str(value or ""))]
    auth_source_configured = _auth_source_configured(values)
    require_auth = str(values.get("ASTRA_REQUIRE_AUTH", "")).strip().lower() in TRUE_VALUES
    local_backend = str(values.get("BACKEND_URL", "")).startswith("http://localhost")
    local_frontend = str(values.get("FRONTEND_URL", "")).startswith("http://localhost")
    # Hostname alone can't tell a locked-down production deploy from a real,
    # non-localhost staging box (e.g. an IP+nip.io host) that was never meant to
    # carry live Stripe/NextAuth secrets — ASTRA_REQUIRE_AUTH is the deliberate
    # signal an operator actually flips on for a real production deployment, so
    # gate the strict secrets checklist on that too, not hostname string-matching
    # alone (a real production deploy with ASTRA_REQUIRE_AUTH=true still gets the
    # full check).
    local_mode = local_backend or local_frontend or not require_auth
    wildcard_cors = "*" in str(values.get("ASTRA_CORS_ORIGINS", ""))
    trust_headers = str(values.get("ASTRA_TRUST_AUTH_HEADERS", "")).strip().lower() in TRUE_VALUES
    errors: list[str] = []
    warnings: list[str] = []
    if require_auth and not auth_source_configured:
        errors.append("ASTRA_REQUIRE_AUTH is enabled but no JWT secret/JWKS URL/trusted header auth source is configured.")
    if require_auth and wildcard_cors:
        errors.append("ASTRA_CORS_ORIGINS cannot contain '*' when auth is enabled.")
    if require_auth and trust_headers:
        warnings.append("ASTRA_TRUST_AUTH_HEADERS is enabled; only safe behind a trusted auth proxy.")
    if not local_mode:
        if missing:
            errors.append(f"Missing required production env keys: {', '.join(sorted(missing))}.")
        if placeholders:
            errors.append(f"Placeholder production values detected: {', '.join(sorted(placeholders))}.")
    return {
        "ok": not errors,
        "mode": "local" if local_mode else "production",
        "missing": sorted(missing),
        "placeholder_values": sorted(placeholders),
        "auth_source_configured": auth_source_configured,
        "warnings": warnings,
        "errors": errors,
        "summary": (
            "Runtime settings look production-safe."
            if not errors
            else f"Runtime settings failed {len(errors)} production validation check(s)."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit production .env keys without printing secret values.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--print-missing-template", action="store_true")
    parser.add_argument("--write-missing-template", default="")
    args = parser.parse_args()

    if args.print_missing_template:
        print(render_missing_env_template(args.env_file), end="")
        return 0

    if args.write_missing_template:
        target = Path(args.write_missing_template)
        target.write_text(render_missing_env_template(args.env_file))
        print(json.dumps({"ok": True, "wrote": str(target)}, indent=2, sort_keys=True))
        return 0

    result = audit_env_file(args.env_file)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
