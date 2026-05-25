"""Technical specialist — GitHub, Supabase, Vercel, Clerk, Cloudflare, PostHog, Clarity, Claude Code."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.github_scaffold import github_create_repo
from backend.tools.claude_scaffold import claude_code_scaffold
from backend.tools.vercel_deploy import vercel_deploy_from_github
from backend.tools.supabase_tools import (
    supabase_create_project,
    supabase_create_table, supabase_enable_rls,
    supabase_setup_auth, supabase_create_storage_bucket, supabase_generate_schema,
)
from backend.tools.clerk_tools import clerk_generate_integration, clerk_generate_webhook_handler
from backend.tools.cloudflare_tools import (
    cloudflare_create_dns_record, cloudflare_setup_vercel_domain,
    cloudflare_setup_email_dns, cloudflare_generate_instructions,
)
from backend.tools.posthog_tools import posthog_generate_integration, posthog_create_key_events_spec
from backend.tools.clarity_tools import clarity_generate_integration, clarity_setup_for_app
from backend.tools.composio_tools import composio_linear_create_issue, composio_notion_create_page


def build_technical_agent(**kwargs) -> Agent:
    return Agent(
        name="technical",
        role=(
            "You are the technical specialist. Your agent name is 'technical'. "
            "Your prior session notes are pre-loaded in prior_vault_notes in SHARED CONTEXT — read them before acting. "
            "You build and DEPLOY complete production-ready apps automatically. FULL AUTO-DEPLOY WORKFLOW:\n"
            "(1) github_create_repo — create the GitHub repo. Save repo_url.\n"
            "(2) supabase_create_project(project_name=<app-name>) — provision real Supabase DB. "
            "Save project_ref, anon_key, service_role_key, db_connection_string.\n"
            "(3) supabase_generate_schema(app_name, entities) — design DB schema.\n"
            "(4) clerk_generate_integration — auth code (nextjs framework by default).\n"
            "(5) posthog_generate_integration — analytics.\n"
            "(6) clarity_setup_for_app — session recording.\n"
            "(7) claude_code_scaffold(repo_url=<step1 repo_url>, task=<full spec>, context=<JSON of all prior results including Supabase keys, schema, Clerk code, PostHog>) "
            "— builds real working code WITH env vars pre-configured and pushes to GitHub.\n"
            "(8) vercel_deploy_from_github(repo_url=<step1 repo_url>, project_name=<slug>, "
            "env_vars={NEXT_PUBLIC_SUPABASE_URL: <url>, NEXT_PUBLIC_SUPABASE_ANON_KEY: <key>, "
            "SUPABASE_SERVICE_ROLE_KEY: <key>, DATABASE_URL: <connection_string>, ...all other keys}) "
            "— links GitHub repo to Vercel and DEPLOYS. The app is live. Save deployment_url.\n"
            "(9) cloudflare_setup_vercel_domain — wire custom DNS if domain was provided.\n"
            "(10) composio_linear_create_issue for 3 MVP next-step tickets.\n"
            "(11) obsidian_log then done.\n"
            "CRITICAL: Steps 1-8 are MANDATORY for any app-building task. "
            "Always pass ALL Supabase keys and other service credentials into vercel_deploy_from_github env_vars "
            "so the deployed app is fully configured. The founder should get a live URL, not setup instructions."
        ),
        tools={
            "github_create_repo": github_create_repo,
            "claude_code_scaffold": claude_code_scaffold,
            "vercel_deploy_from_github": vercel_deploy_from_github,
            "supabase_create_project": supabase_create_project,
            "supabase_generate_schema": supabase_generate_schema,
            "supabase_create_table": supabase_create_table,
            "supabase_enable_rls": supabase_enable_rls,
            "supabase_setup_auth": supabase_setup_auth,
            "supabase_create_storage_bucket": supabase_create_storage_bucket,
            "clerk_generate_integration": clerk_generate_integration,
            "clerk_generate_webhook_handler": clerk_generate_webhook_handler,
            "cloudflare_setup_vercel_domain": cloudflare_setup_vercel_domain,
            "cloudflare_create_dns_record": cloudflare_create_dns_record,
            "cloudflare_generate_instructions": cloudflare_generate_instructions,
            "posthog_generate_integration": posthog_generate_integration,
            "posthog_create_key_events_spec": posthog_create_key_events_spec,
            "clarity_setup_for_app": clarity_setup_for_app,
            "clarity_generate_integration": clarity_generate_integration,
            "composio_linear_create_issue": composio_linear_create_issue,
            "composio_notion_create_page": composio_notion_create_page,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
