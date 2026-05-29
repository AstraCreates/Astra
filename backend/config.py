from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""
    redis_url: str = "redis://localhost:6379"
    gemini_api_key: str = ""
    agent_model_base_url: str = "https://api.deepinfra.com/v1/openai"
    agent_model_api_key: str = ""
    agent_model_name: str = "deepseek-ai/DeepSeek-V4-Flash"
    # Planner uses a stronger model for task decomposition
    planner_model_base_url: str = "https://api.deepinfra.com/v1/openai"
    planner_model_api_key: str = ""
    planner_model_name: str = "meta-llama/Llama-4-Scout-17B-16E-Instruct"
    # Lighter model for non-reasoning agents (design)
    light_model_base_url: str = "https://api.deepinfra.com/v1/openai"
    light_model_name: str = "deepseek-ai/DeepSeek-V4-Flash"
    # High-output model for docs/copy/HTML (small input, large output, non-coding)
    highoutput_model_base_url: str = "https://api.deepinfra.com/v1/openai"
    highoutput_model_name: str = "deepseek-ai/DeepSeek-V4-Flash"
    vertex_project: str = ""
    vertex_location: str = "us-central1"

    # Deployment tools
    vercel_token: str = ""
    github_token: str = ""

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

    # Stripe Standard Connect
    stripe_secret_key: str = ""
    stripe_client_id: str = ""
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

    # Obsidian vault — agents write session logs here (separate from user's personal vault)
    obsidian_vault: str = "~/agent-workspace"

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
