import re

from pydantic_settings import BaseSettings

# Field-name substrings that mark a value as a credential. Used to redact
# Settings' repr/str — this class holds ~30 live API keys/tokens/secrets as
# plain strings, and pydantic's default repr prints every field verbatim.
# That's exactly how a real OpenRouter/GitHub/Supabase/Gemini/Vercel/SendGrid/
# Composio/Clerk key + a test-email IMAP password ended up in plaintext in an
# AttributeError message during a test run. Redact by name pattern (not a
# per-field allowlist) so a newly added secret field is covered automatically.
_SECRET_FIELD_RE = re.compile(
    r"key|secret|token|password|pass$|_sid$|card_number|card_expiry|card_name|billing_",
    re.IGNORECASE,
)


class Settings(BaseSettings):
    def __repr_args__(self):
        return [
            (name, "***REDACTED***" if value and _SECRET_FIELD_RE.search(name) else value)
            for name, value in super().__repr_args__()
        ]

    supabase_url: str = ""
    supabase_key: str = ""
    # Heavy coder for broad end-to-end builds outside the technical specialist's new
    # "medium brain + light workers" lane. Kept for web/ops/full-build fallback paths.
    mvp_build_model: str = "deepseek/deepseek-v4-pro"
    # Web-search/research model. perplexity/sonar ($1/$1), NOT sonar-pro ($3/$15) — the
    # pro tier's $15/M output made it 36% of prod spend for marginal research-depth gain.
    research_model: str = "perplexity/sonar"
    # Wrapper model for research specialists. This is separate from
    # research_model, which is the internal web-research synthesis model.
    # Swapped from ling-2.6-flash to deepseek-v4-flash for more reliable tool
    # calling -- ling was producing malformed/truncated tool-call JSON
    # (confirmed live: research_competitors repeatedly hit its output-token
    # cap and, on one attempt, recovered a parsed action missing its "tool"
    # field entirely). In practice this default is usually shadowed by
    # factory.py's _small_kwargs (itself driven by the OR_LIGHT_MODEL env
    # var), which is also being swapped -- kept in sync here for any caller
    # that constructs a research agent directly, bypassing the factory.
    research_agent_model: str = "deepseek/deepseek-v4-flash"
    # Stable profile for Company OS deep research. Operator fallback remains
    # explicit; a failed attempt must not silently change model identity.
    deep_research_model: str = "deepseek/deepseek-v4-flash"
    deep_research_max_attempts: int = 2
    deep_research_backoff_seconds: float = 1.0
    deep_research_timeout_seconds: int = 900
    # Company OS copilot intent classification (typo-correction + multi-step
    # splitting + department routing in one call). Validated on a 1200-case
    # combinatorial test set: 100% accuracy, ~0.3s avg latency, honors
    # reasoning:none (zero wasted reasoning tokens, unlike nex-agi/nex-n2-mini
    # which was tested and rejected for burning 260-580 tokens on hidden
    # reasoning per call despite the same flag). Pinned explicitly, not
    # routed through the general-purpose or_* lanes -- this is a specific,
    # validated model choice for a specific task, not interchangeable.
    intent_classifier_model: str = "poolside/laguna-xs-2.1"
    company_os_stale_task_seconds: int = 1800
    # Cheap native-search model for the bounded research discovery pass. The
    # agent model still synthesizes the returned evidence; this model handles
    # live retrieval through OpenRouter's provider-native web search.
    # gemini-2.5-flash-lite over gpt-4o-mini-search-preview: native Google Search
    # grounding (vs relying on prompt-delivered payloads) and a 1M-token context
    # window, which matters when a research round's evidence blocks span many
    # sources. Enabled by default -- this replaces the crw+searxng+lightpanda
    # scrape pipeline as deep_research's primary path (see deep_research's own
    # comment: crw has no chrome/JS-renderer tier deployed, so anti-bot-heavy
    # pages routinely timed out under concurrent multi-lane research).
    native_research_model: str = "openai/gpt-4o-mini-search-preview"
    # Disabled: grounded-search LLM round trips per query got too expensive in
    # practice. run_research_pipeline() falls back to the free DDGS-based
    # batch_search/search_and_fetch path below (browser_research.py:1520-1527)
    # when this is off -- same output shape, no paid model call.
    native_research_enabled: bool = False
    # Which coding-agent CLI drives MVP builds: "caveman" (@juliusbrussee/caveman-code,
    # ~2x fewer tokens, native openrouter provider) or "openclaude" (legacy fallback).
    code_agent: str = "caveman"
    # Technical wrapper/orchestrator model. This is the agent that plans work,
    # reasons about architecture, decides when to delegate, and supervises QA/fix loops.
    technical_agent_model: str = "xiaomi/mimo-v2.5"
    # Primary coding model for the technical lane itself. This is intentionally a
    # medium model: strong enough to implement cohesive features end-to-end, but
    # cheaper than the heavyweight MVP builder. The technical agent can then fan
    # out smaller, isolated code tasks to lighter worker coders below.
    technical_build_model: str = "xiaomi/mimo-v2.5"
    # Light coding worker model used for delegated / parallelized technical sub-builds
    # such as auth screens, isolated dashboard modules, spot fixes, and narrow patches.
    technical_subagent_model: str = "inclusionai/ling-2.6-flash"
    # 20 was too tight for multi-step builds (resolve → run_mvp_loop → provision
    # → QA → fix rounds → obsidian_log → done). 30 gives enough headroom for a
    # full build + one round of error recovery without hitting max_iterations.
    technical_agent_max_iterations: int = 30
    # Web agent wrapper model (drives its tool calls: repo create, run_mvp_loop).
    web_agent_model: str = "inclusionai/ling-2.6-flash"
    # Use a stronger native tool-calling model only for the small set of agents
    # that orchestrate many heterogeneous tools / side effects. Keep this
    # separate from the cheaper default light lane because gpt-oss-120b is
    # materially more expensive than Ling/Flash and should stay narrowly scoped.
    tool_heavy_agent_model: str = "openai/gpt-oss-120b"
    mvp_max_completion_rounds: int = 1
    # Compiler-as-critic recovery: re-run `npm run build`, feed real errors to the
    # coder, re-verify — up to this many rounds before giving up.
    mvp_max_build_rounds: int = 3
    # Hard ceiling on cumulative input+output tokens for a single build subprocess
    # call (_run_claude/_run_caveman). caveman-code's own internal tool-use loop is
    # otherwise unbounded — a real production build hit 3.99M tokens in one call.
    # Killed mid-stream once crossed; generous enough not to cut normal builds.
    mvp_max_build_tokens: int = 1_500_000
    # Kill switch for the headroom pipeline tuning monkeypatch (agent.py
    # _tune_headroom_pipeline_once) — it reaches past headroom-ai's public
    # compress() API into its private pipeline singleton, which is not a
    # supported integration point. Real incident 2026-07-10: opening the
    # protect-everything default made the ContentRouter's ModernBERT
    # (Kompress) text compressor actually engage under real traffic for the
    # first time — that's real local CPU inference, not an API call, and it
    # pegged the backend container's CPU and permanently grew its resident
    # memory (model stays loaded for the process lifetime), making the whole
    # site unresponsive. Defaults OFF until Kompress's real resource cost is
    # measured properly; flip on via env HEADROOM_TUNING_ENABLED=true.
    headroom_tuning_enabled: bool = False
    # How much of a conversation to expose to compression (was hardcoded 0.3,
    # the value implicated in the 2026-07-10 incident). Lower = less content
    # routed through the real local Kompress/ModernBERT inference per call,
    # which scales down the CPU cost — but does NOT avoid the one-time
    # memory cost of loading the model at all once any content is exposed,
    # since that happens as soon as this is > 0. Tune via env
    # HEADROOM_PROTECT_RECENT_READS_FRACTION.
    headroom_protect_recent_reads_fraction: float = 0.1
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
    or_light_model: str = "inclusionai/ling-2.6-flash"
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
    light_model_name: str = "inclusionai/ling-2.6-flash"
    # High-output model — DeepSeek Flash (65k max output vs qwen3-235b's 16k ceiling)
    highoutput_model_base_url: str = "https://openrouter.ai/api/v1"
    highoutput_model_name: str = "deepseek/deepseek-v4-flash"
    # Self-hosted crw (Firecrawl-alternative search+scrape) backing the
    # recursive research replacement for Perplexity Sonar. Single call does
    # search + scrape via scrapeOptions — see backend/tools/browser_research.py.
    crw_base_url: str = "http://crw:3000"
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
    # Comma-separated tester emails allowed to use the app at all, for a
    # gated beta launch. Empty = allow everyone (matches astra_platform_admins'
    # unset-is-permissive convention) — set once a real allowlist is needed.
    astra_beta_allowlist: str = ""
    astra_storage_backend: str = "local"
    astra_alert_webhook_url: str = ""
    astra_alert_min_severity: str = "warning"
    astra_runtime_guardrails: bool = True
    astra_tool_registry_v2: bool = False
    # NOTE: rollout.enabled() reads astra_<feature> off this Settings object. A flag
    # whose field is NOT declared here can never turn on, even with ASTRA_<FEATURE>=true
    # in .env (extra="ignore" drops it). context_compression_v2 was off for exactly this
    # reason — agent conversations grew unbounded (marketing hit 212k tokens/call).
    astra_context_compression_v2: bool = True
    astra_context_compression_v2_rollout_percent: int = 100
    # Same declare-or-silently-off rule as compression. native_tool_calls switches
    # agents from JSON-in-prompt to provider-native function-calling (all our agent
    # models support it); delegation_v2 + skill_review change sub-agent / review paths.
    # (specialist_manifests + shadow_runtime have no code readers — intentionally not
    # declared; declaring them would do nothing.)
    astra_native_tool_calls: bool = True
    astra_native_tool_calls_rollout_percent: int = 100
    astra_delegation_v2: bool = False
    astra_skill_review: bool = False
    # Wave 1 control plane (PLAN.md). Same declare-or-silently-off rule as
    # above. All default OFF/0 -- unlike the mature flags above, none of
    # these back a proven system yet; nothing reads them this wave.
    # Temporal is the canonical engine for new runs. Legacy remains readable
    # for pre-cutover runs, but new assignments must not silently land there.
    astra_control_plane_v2: bool = True
    astra_control_plane_v2_rollout_percent: int = 100
    # Percentage-only: samples eligible runs for Temporal shadow comparison
    # (Wave 3), independent of control_plane_v2 -- a legacy-engine run can
    # still be selected for shadow. No matching bool; the plan caps this at
    # 5% by design ("Sample at most 5% of eligible internal/beta runs").
    astra_temporal_shadow_percent: int = 0
    astra_event_stream_v2: bool = False
    astra_event_stream_v2_rollout_percent: int = 0
    astra_model_gateway_v2: bool = False
    astra_model_gateway_v2_rollout_percent: int = 0
    # Wave 5.1: LiteLLM proxy sits between Astra and Headroom/OpenRouter, gated per-run
    # by model_gateway_v2 (see backend/control_plane/gateway.py). Service name matches
    # the litellm docker-compose entry; not reachable outside the compose network.
    litellm_gateway_base_url: str = "http://litellm:4000"
    litellm_master_key: str = ""
    # Optional JSON object mapping org/founder IDs to LiteLLM virtual keys.
    # This lets production route different orgs through distinct gateway keys
    # without changing the code path that calls get_gateway_client().
    litellm_org_keys_json: str = ""
    # Production safety valve (PLAN.md): once true, a model_gateway_v2 run that can't
    # reach the gateway fails loud instead of silently falling back to the direct
    # OpenRouter path -- direct calls bypass LiteLLM's spend tracking entirely, which
    # is exactly the blind spot the gateway exists to close. Stays False in dev so a
    # laptop without a running litellm container doesn't break agent calls.
    astra_direct_provider_disabled: bool = False
    astra_research_engine_v2: bool = False
    astra_research_engine_v2_rollout_percent: int = 0
    astra_brain_v2: bool = False
    astra_brain_v2_rollout_percent: int = 0
    astra_brain_graph_driver: str = "falkordblite"
    astra_brain_graph_path: str = ".astra/graphiti/company_brain.db"
    astra_brain_graph_host: str = "localhost"
    astra_brain_graph_port: int = 6379
    astra_brain_graph_username: str = ""
    astra_brain_graph_password: str = ""
    astra_brain_graph_database: str = "astra_company_brain"
    astra_brain_graph_api_key: str = ""
    astra_brain_graph_base_url: str = ""
    astra_brain_graph_model: str = "openai/gpt-4.1-mini"
    astra_brain_graph_small_model: str = "openai/gpt-4.1-mini"
    astra_brain_graph_embedding_model: str = "text-embedding-3-small"
    # Simple on/off, no percent rollout -- Langfuse hooks are implemented but
    # stay disabled until a separate resource benchmark passes.
    astra_langfuse_enabled: bool = False
    # Wave 5.2: OTLP/HTTP collector endpoint (e.g. http://otel-collector:4318/v1/traces).
    # Empty = tracing runs in console-only mode, no network export -- see
    # backend/observability/tracing.py::init_tracing. OTel is mandatory (unlike
    # Langfuse above); this just controls where spans go, not whether they exist.
    otel_exporter_endpoint: str = ""
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
    # Explicit CORS allow-list (comma-separated origins, e.g.
    # "https://astracreates.com,https://www.astracreates.com"). Browsers send an
    # Origin header CORS checks against this list; combined with header-based auth
    # (x-astra-user-id) a wildcard here would let any website drive the API using a
    # visitor's own session, so this must never be "*" in prod. Defaults to the local
    # Next.js dev origin only. NOTE: declared here so it isn't silently dropped by
    # extra="ignore" — same rule as the astra_<feature> flags above.
    astra_cors_origins: str = "http://localhost:3000"

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

    # Automation runtime
    automation_provider: str = "windmill"
    automation_base_url: str = "http://windmill-server:8000/api"
    automation_workspace: str = "admins"
    automation_token: str = ""

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
