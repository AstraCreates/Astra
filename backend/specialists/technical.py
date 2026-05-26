"""Technical specialist — builds a real MVP: GitHub repo, code, Supabase, Vercel deploy."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.github_scaffold import github_create_repo
from backend.tools.git_tools import write_files_to_repo, run_claude_in_repo
from backend.tools.vercel_deploy import vercel_deploy_from_github
from backend.tools.supabase_tools import (
    supabase_create_project,
    supabase_create_table, supabase_enable_rls,
    supabase_setup_auth, supabase_create_storage_bucket, supabase_generate_schema,
)
from backend.tools.clerk_tools import clerk_generate_integration, clerk_generate_webhook_handler
from backend.tools.cloudflare_tools import (
    cloudflare_setup_vercel_domain,
    cloudflare_generate_instructions,
)
from backend.tools.posthog_tools import posthog_generate_integration
from backend.tools.composio_tools import composio_linear_create_issue, composio_notion_create_page


def build_technical_agent(**kwargs) -> Agent:
    return Agent(
        name="technical",
        role=(
            "You are a technical specialist. Your job is to BUILD a real working MVP and push it to GitHub — "
            "not just scaffold, not just describe. Actual working code.\n\n"
            "WORKFLOW — follow this exact sequence:\n"
            "1. obsidian_read(founder_id=<FOUNDER_ID>, session_id=<SESSION>) — read research notes to understand the product\n"
            "2. github_create_repo(name=<product-name>, description=<description>, founder_id=<FOUNDER_ID>) — create repo\n"
            "3. run_claude_in_repo(repo_url=<url>, task='Build complete Next.js 14 app with app router, all pages, components, and Tailwind CSS for: <product>', session_id=<SESSION>, context=<research notes>)\n"
            "4. run_claude_in_repo(repo_url=<url>, task='Build FastAPI backend with all endpoints, Pydantic models, and business logic for: <product>', session_id=<SESSION>)\n"
            "5. run_claude_in_repo(repo_url=<url>, task='Add Clerk auth, Supabase client, environment config (.env.example), and docker-compose.yml', session_id=<SESSION>)\n"
            "6. run_claude_in_repo(repo_url=<url>, task='Add README.md with setup instructions, fix any TypeScript errors, ensure all imports resolve', session_id=<SESSION>)\n"
            "7. vercel_deploy_from_github(repo_url=<url>, founder_id=<FOUNDER_ID>) — deploy\n"
            "8. obsidian_log — log repo URL, deploy URL, features built\n"
            "9. done — return {repo_url, deploy_url, features_built: [...]}\n\n"
            "run_claude_in_repo runs Claude Code inside the cloned repo — it writes real files and commits. "
            "Call it multiple times, each adds more features. Always use the same session_id so calls share the clone. "
            "write_files_to_repo(repo_url, files={'path/file.ext': 'content'}, session_id) writes specific files directly. "
            "supabase_generate_schema designs the DB schema if needed. "
            "Do NOT stop after step 2 — the repo must have real code, not just be empty."
        ),
        tools={
            "github_create_repo": github_create_repo,
            "run_claude_in_repo": run_claude_in_repo,
            "write_files_to_repo": write_files_to_repo,
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
            "cloudflare_generate_instructions": cloudflare_generate_instructions,
            "posthog_generate_integration": posthog_generate_integration,
            "composio_linear_create_issue": composio_linear_create_issue,
            "composio_notion_create_page": composio_notion_create_page,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
