from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""
    # Model that drives the coding agent (caveman) for technical-agent MVP builds.
    # deepseek-v4-pro ($0.435/$0.870) — still ~3× cheaper input than GLM-5.2 ($1.2) which
    # was 46% of prod spend, and native function-calls in caveman. NOT qwen3-coder-FLASH:
    # it emits XML-text tool calls (<function=write>...) caveman can't parse → 0 tools run.
    mvp_build_model: str = "deepseek/deepseek-v4-pro"
    # Web-search/research model. perplexity/sonar ($1/$1), NOT sonar-pro ($3/$15) — the
    # pro tier's $15/M output made it 36% of prod spend for marginal research-depth gain.
    research_model: str = "perplexity/sonar"
    # Which coding-agent CLI drives MVP builds: "caveman" (@juliusbrussee/caveman-code,
    # ~2x fewer tokens, native openrouter provider) or "openclaude" (legacy fallback).
    code_agent: str = "caveman"
    # Technical wrapper orchestrates a multi-step workflow (build → provision infra via
    # browser → self-QA the live site → fix), so it gets a smart model for reliable
    # tool decisions; the heavy code generation is still done by mvp_build_model in
    # run_mvp_loop / openclaude. Few wrapper calls, so the cost impact is small.
    # Flash not Pro: the wrapper loop has no prompt caching wired, Pro's $0.435/M
    # input rate is wasteful for ~20 orchestration calls per build.
    # Bench v11 (2026-06-26, ACES): MiMo-V2.5 #1 (ACES=5661, P_hard=0.98, $0.0003/suc).
    # Thinking-on in prod (mimo exempt from effort:none suppression in llm_cache.py).
    technical_agent_model: str = "xiaomi/mimo-v2.5"
    # 20 was too tight for multi-step builds (resolve → run_mvp_loop → provision
    # → QA → fix rounds → obsidian_log → done). 30 gives enough headroom for a
    # full build + one round of error recovery without hitting max_iterations.
    technical_agent_max_iterations: int = 30
    # Web agent wrapper model (drives its tool calls: repo create, run_mvp_loop).
    web_agent_model: str = "deepseek/deepseek-v4-flash"
    mvp_max_completion_rounds: int = 1
    # Compiler-as-critic recovery: re-run `npm run build`, feed real errors to the
    # coder, re-verify — up to this many rounds before giving up.
    mvp_max_build_rounds: int = 3
    # DeepSeek Flash: planning writes long outputs; MiMo's $2.82/M output rate
    # dominates cost at scale. Flash handles plan-length output at $1.72/M.
    build_plan_model: str = "deepseek/deepseek-v4-flash"
    # MVP builds (openclaude tool-use) are billed as separate, higher-rate
    # credits — this multiplier is applied to the build's token-based credit cost.
    mvp_credit_multiplier: float = 3.0
    redis_url: str = "redis://localhost:6379"
    gemini_api_key: str = ""
    agent_model_base_url: str = "https://openrouter.ai/api/v1"
    agent_model_api_key: str = ""
    agent_model_name: str = "deepseek/deepseek-v4-flash"
    # OpenRouter — NOT overridden by Coolify (new field names)
    openrouter_api_key: str = ""
    openrouter_api_key_2: str = ""
    openrouter_api_key_3: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # DeepSeek Flash: long planner outputs at $2.82/M (MiMo) → $1.72/M.
    or_planner_model: str = "deepseek/deepseek-v4-flash"
    # Bench v2 (2026-06-26, LLM-judge): DeepSeek Flash 4.33/5 on NDA + pitch + finance
    # at QAC $0.261/1k. Qwen3-235b was $0.176/1k but capped at 16k max output — truncates
    # long financial models. DeepSeek Flash has 65k output / 1M context, no ceiling issue.
    or_highoutput_model: str = "deepseek/deepseek-v4-flash"
    # DeepSeek Flash: Qwen3-235b-T won bench on quality but runs full thinking (exempt
    # from effort:none), billing thinking tokens as output at $3.34/M — 17% of prod spend.
    # Flash ($1.72/M output, no thinking overhead) cuts this line to ~$0.50/M effective.
    or_light_model: str = "deepseek/deepseek-v4-flash"
    tooluse_model_base_url: str = "https://openrouter.ai/api/v1"
    tooluse_model_name: str = "deepseek/deepseek-v4-flash"
    # Web-search synthesis model — uncached, so input price dominates.
    # Used by web_search.py deep_research → Flash is 4.4× cheaper input
    # than Pro for synthesis calls.
    planner_model_base_url: str = "https://openrouter.ai/api/v1"
    planner_model_api_key: str = ""
    planner_model_name: str = "deepseek/deepseek-v4-flash"
    # Chat model — DeepSeek V4 Flash: chat endpoint has no prompt caching; Flash
    # is 4.4× cheaper on fresh input than Pro with equivalent chat quality.
    chat_model_base_url: str = "https://openrouter.ai/api/v1"
    chat_model_api_key: str = ""
    chat_model_name: str = "deepseek/deepseek-v4-flash"
    light_model_base_url: str = "https://openrouter.ai/api/v1"
    light_model_name: str = "deepseek/deepseek-v4-flash"
    # High-output model — DeepSeek Flash (65k max output vs qwen3-235b's 16k ceiling)
    highoutput_model_base_url: str = "https://openrouter.ai/api/v1"
    highoutput_model_name: str = "deepseek/deepseek-v4-flash"
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

    # Composio — legacy, not used for new integrations
    composio_api_key: str = ""

    # LinkedIn OAuth
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""

    # Credential store encryption key — generated once and fixed in .env
    astra_creds_key: str = ""
    astra_require_auth: bool = True
    astra_trust_auth_headers: bool = False  # must be False in prod; JWT Bearer is the only verified path
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
    # NOTE: rollout.enabled() reads astra_<feature> off this Settings object. A flag
    # whose field is NOT declared here can never turn on, even with ASTRA_<FEATURE>=true
    # in .env (extra="ignore" drops it). context_compression_v2 was off for exactly this
    # reason — agent conversations grew unbounded (marketing hit 212k tokens/call).
    astra_context_compression_v2: bool = False
    # Same declare-or-silently-off rule as compression. native_tool_calls switches
    # agents from JSON-in-prompt to provider-native function-calling (all our agent
    # models support it); delegation_v2 + skill_review change sub-agent / review paths.
    # (specialist_manifests + shadow_runtime have no code readers — intentionally not
    # declared; declaring them would do nothing.)
    astra_native_tool_calls: bool = False
    astra_delegation_v2: bool = False
    astra_skill_review: bool = False
    astra_fallback_model: str = "moonshotai/kimi-k2.5"
    # Self-host stub: when True, agent calls route to local inference (SELF_HOST_BASE_URL /
    # SELF_HOST_MODEL). Set ASTRA_SELF_HOST=true + SELF_HOST_BASE_URL=http://localhost:8080/v1
    # + SELF_HOST_MODEL=<loaded model name> to switch to local GPU inference.
    # Also raise ASTRA_COMPRESSION_THRESHOLD=262144 when self-hosting (256K context fits).
    astra_self_host: bool = False
    self_host_base_url: str = ""
    self_host_model: str = ""

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
