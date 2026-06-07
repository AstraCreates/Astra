from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""
    # When false, the outreach subsystem uses the free file-backed store instead
    # of Supabase. Set OUTREACH_USE_SUPABASE=true only with a reachable project.
    outreach_use_supabase: bool = False
    # Model that drives openclaude for technical-agent MVP builds. Must be a
    # strong agentic/tool-use model (DeepSeek-V4-Flash chats instead of building).
    mvp_build_model: str = "tencent/hy3-preview"
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
    or_planner_model: str = "tencent/hy3-preview"
    or_highoutput_model: str = "tencent/hy3-preview"
    or_light_model: str = "xiaomi/mimo-v2.5"
    # Tool-use model — hy3-preview for web agent (strong agentic workflows)
    tooluse_model_base_url: str = "https://openrouter.ai/api/v1"
    tooluse_model_name: str = "tencent/hy3-preview"
    # Planner — hy3-preview: $0.063/$0.21/M, reasoning MoE, 262k ctx
    planner_model_base_url: str = "https://openrouter.ai/api/v1"
    planner_model_api_key: str = ""
    planner_model_name: str = "tencent/hy3-preview"
    # Chat model — hy3-preview
    chat_model_base_url: str = "https://openrouter.ai/api/v1"
    chat_model_api_key: str = ""
    chat_model_name: str = "tencent/hy3-preview"
    # Light model — MiMo: cheap, fast for research and short repeated tasks
    light_model_base_url: str = "https://openrouter.ai/api/v1"
    light_model_name: str = "xiaomi/mimo-v2.5"
    # High-output model — hy3-preview via OpenRouter
    highoutput_model_base_url: str = "https://openrouter.ai/api/v1"
    highoutput_model_name: str = "tencent/hy3-preview"
    vertex_project: str = ""
    vertex_location: str = "us-central1"

    # Deployment tools
    vercel_token: str = ""
    github_token: str = ""

    # GitHub OAuth App — for one-click token generation via OAuth flow
    github_client_id: str = ""
    github_client_secret: str = ""

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
    astra_require_auth: bool = False
    astra_trust_auth_headers: bool = False
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
    nwra_card_cvv: str = ""
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
    browser_use_model: str = "google/gemini-2.5-flash"
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

    # Frontend env vars that may leak into .env — ignored by backend
    next_public_clerk_publishable_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
