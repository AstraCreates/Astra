from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""
    # Model that drives openclaude for technical-agent MVP builds. Must be a
    # strong agentic/tool-use model (DeepSeek-V4-Flash chats instead of building).
    mvp_build_model: str = "xiaomi/mimo-v2.5-pro"
    # Technical wrapper orchestrates a multi-step workflow (build → provision infra via
    # browser → self-QA the live site → fix), so it gets the smart model for reliable
    # tool decisions; the heavy code generation is still done by mvp_build_model in
    # run_mvp_loop / openclaude. Few wrapper calls, so the cost impact is small.
    technical_agent_model: str = "deepseek/deepseek-v4-pro"
    # 12 was too tight: the build workflow (resolve repo → run_mvp_loop →
    # provision → QA → obsidian_log → done) plus tool-failure retries blew the
    # cap and force-synthesized BEFORE deploy/log finished. 20 matches the other
    # build-heavy agents (legal 20, finance/marketing 20-25).
    technical_agent_max_iterations: int = 20
    # Web agent wrapper model (drives its tool calls: repo create, run_mvp_loop).
    # Dedicated so it isn't pinned by the env-overridden or_planner_model (hy3).
    web_agent_model: str = "xiaomi/mimo-v2.5-pro"
    mvp_max_completion_rounds: int = 1
    # Compiler-as-critic recovery: re-run `npm run build`, feed real errors to the
    # coder, re-verify — up to this many rounds before giving up.
    mvp_max_build_rounds: int = 3
    # Model that produces the COMPLETE build spec (pages, data model, features, file
    # plan) before web/technical agents build, so the build follows a real plan
    # instead of a one-line goal. MiniMax-M3 = strong long-form planning/reasoning.
    build_plan_model: str = "minimax/minimax-m3"
    # MVP builds (openclaude tool-use) are billed as separate, higher-rate
    # credits — this multiplier is applied to the build's token-based credit cost.
    mvp_credit_multiplier: float = 3.0
    redis_url: str = "redis://localhost:6379"
    gemini_api_key: str = ""
    agent_model_base_url: str = "https://openrouter.ai/api/v1"
    agent_model_api_key: str = ""
    agent_model_name: str = "xiaomi/mimo-v2.5"
    # OpenRouter — NOT overridden by Coolify (new field names)
    openrouter_api_key: str = ""
    openrouter_api_key_2: str = ""
    openrouter_api_key_3: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    or_planner_model: str = "deepseek/deepseek-v4-pro"
    or_highoutput_model: str = "deepseek/deepseek-v4-pro"
    or_light_model: str = "xiaomi/mimo-v2.5"
    # Tool-use model — DeepSeek V4 Flash (strong agentic/tool-calling, 1M ctx)
    tooluse_model_base_url: str = "https://openrouter.ai/api/v1"
    tooluse_model_name: str = "deepseek/deepseek-v4-pro"
    # Planner — DeepSeek V4 Pro: $0.435/$0.87/M, cache read $0.0036/M (5x cheaper
    # cached than V4 Flash), Intelligence Index 52, 1M ctx, strong tool calling
    # (replaced hy3-preview, which mangled tool calls and never finished tasks).
    planner_model_base_url: str = "https://openrouter.ai/api/v1"
    planner_model_api_key: str = ""
    planner_model_name: str = "deepseek/deepseek-v4-pro"
    # Chat model — DeepSeek V4 Flash
    chat_model_base_url: str = "https://openrouter.ai/api/v1"
    chat_model_api_key: str = ""
    chat_model_name: str = "deepseek/deepseek-v4-pro"
    # Light model — MiMo: cheap, fast for research and short repeated tasks
    light_model_base_url: str = "https://openrouter.ai/api/v1"
    light_model_name: str = "xiaomi/mimo-v2.5"
    # High-output model — DeepSeek V4 Flash via OpenRouter
    highoutput_model_base_url: str = "https://openrouter.ai/api/v1"
    highoutput_model_name: str = "deepseek/deepseek-v4-pro"
    vertex_project: str = ""
    vertex_location: str = "us-central1"

    # Deployment tools
    vercel_token: str = ""
    github_token: str = ""

    # GitHub OAuth App — for one-click token generation via OAuth flow
    github_client_id: str = ""
    github_client_secret: str = ""

    # Google OAuth — for sanctioned Gmail API mailbox access.
    google_client_id: str = ""
    google_client_secret: str = ""

    # Vercel OAuth Integration — for one-click token generation via OAuth flow
    vercel_client_id: str = ""
    vercel_client_secret: str = ""

    # Marketing / social
    sendgrid_api_key: str = ""
    meta_access_token: str = ""
    meta_ad_account_id: str = ""
    instagram_access_token: str = ""
    instagram_business_account_id: str = ""

    # Composio — replaces per-service OAuth for Gmail, LinkedIn, GitHub, Calendar, Notion
    composio_api_key: str = ""

    # Credential store encryption key — generated once and fixed in .env
    astra_creds_key: str = ""
    astra_require_auth: bool = True
    astra_trust_auth_headers: bool = True   # header-based identity trusted until JWT is wired
    astra_allow_dev_auth: bool = False
    astra_jwt_issuer: str = ""
    astra_jwt_audience: str = ""
    astra_jwt_jwks_url: str = ""
    astra_jwt_secret: str = ""
    # Comma-separated user IDs allowed to access platform-wide admin endpoints.
    # In local dev with auth disabled, admin endpoints remain available.
    astra_platform_admins: str = ""
    astra_storage_backend: str = "local"
    astra_alert_webhook_url: str = ""
    astra_alert_min_severity: str = "warning"
    astra_runtime_guardrails: bool = True
    astra_tool_registry_v2: bool = False
    astra_fallback_model: str = "xiaomi/mimo-v2.5"

    # Stripe Standard Connect
    stripe_secret_key: str = ""
    stripe_client_id: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_team: str = ""
    stripe_price_scale: str = ""
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3003"

    # NWRA LLC filing — Astra's company card (pays for founder's LLC filing)
    nwra_card_number: str = ""
    nwra_card_expiry_month: str = ""
    nwra_card_expiry_year: str = ""
    # nwra_card_cvv intentionally removed — storing CVV at rest violates PCI-DSS
    nwra_card_name: str = ""
    nwra_billing_address: str = ""
    nwra_billing_city: str = ""
    nwra_billing_state: str = ""
    nwra_billing_zip: str = ""

    # Test email — dedicated Gmail for E2E provisioning tests
    test_email_base: str = ""
    test_email_imap_password: str = ""
    test_email_web_password: str = ""

    # Obsidian vault — agents write session logs here (separate from user's personal vault)
    obsidian_vault: str = "~/agent-workspace"

    # Browser-use automation
    browser_headless: bool = True
    # Path to unpacked CapSolver Chrome extension for CAPTCHA bypass (optional)
    capsolver_extension_path: str = ""
    # CapSolver API key — used for headless Turnstile/hCaptcha solving (no extension needed)
    capsolver_api_key: str = ""
    # Residential proxy for stealth browsing (optional — format: http://host:port)
    browser_proxy_server: str = ""
    browser_proxy_username: str = ""
    browser_proxy_password: str = ""
    # Vision model used by browser-use's screenshot→LLM loop
    browser_use_model: str = "google/gemini-2.5-pro"
    # Base dir for per-founder persistent browser sessions
    browser_sessions_dir: str = ""

    # Outreach / prospecting
    hunter_api_key: str = ""
    apollo_api_key: str = ""

    # User-project tool APIs
    resend_api_key: str = ""
    cloudflare_api_token: str = ""
    supabase_management_token: str = ""
    posthog_api_key: str = ""
    posthog_project_id: str = ""
    clerk_secret_key: str = ""
    clerk_webhook_secret: str = ""
    deepinfra_api_key: str = ""
    notion_token: str = ""
    notion_operating_parent_id: str = ""

    # Research provider default.
    # Keep this on "openrouter" unless we explicitly want all default research
    # agents to collapse onto a single local endpoint.
    research_default_provider: str = "openrouter"  # "openrouter" | "local"

    # Local research model — self-hosted Qwen3/llama.cpp endpoint (optional)
    # Only used by default when research_default_provider="local".
    local_research_base_url: str = ""   # e.g. https://xxx.trycloudflare.com/v1
    local_research_model: str = ""      # e.g. Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
    local_research_api_key: str = "none"  # llama.cpp doesn't require auth

    # Ecommerce integrations
    klaviyo_api_key: str = ""
    printful_api_key: str = ""
    lemonsqueezy_api_key: str = ""

    # Local service integrations
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    square_access_token: str = ""
    square_location_id: str = ""
    yelp_api_key: str = ""

    # Frontend env vars that may leak into .env — ignored by backend
    next_public_clerk_publishable_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


_reloaded_settings = Settings()
_existing_settings = globals().get("settings")
if _existing_settings is not None and isinstance(_existing_settings, BaseSettings):
    # Keep object identity stable across importlib.reload(). A number of runtime
    # modules and test fixtures retain a reference to this singleton.
    for _field_name in Settings.model_fields:
        object.__setattr__(
            _existing_settings,
            _field_name,
            getattr(_reloaded_settings, _field_name),
        )
    settings = _existing_settings
else:
    settings = _reloaded_settings


def research_default_is_local() -> bool:
    provider = (settings.research_default_provider or "openrouter").strip().lower()
    if provider != "local":
        return False
    return bool(settings.local_research_base_url and settings.local_research_model)
