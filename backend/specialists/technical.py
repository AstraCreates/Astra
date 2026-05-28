"""Technical specialist — builds real MVP iteratively via Claude Code."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.github_scaffold import github_create_repo
from backend.tools.git_tools import run_mvp_loop, write_files_to_repo, run_claude_in_repo
from backend.tools.vercel_deploy import vercel_deploy_from_github
from backend.tools.supabase_tools import supabase_generate_schema, supabase_create_project
from backend.tools.clerk_tools import clerk_generate_integration
from backend.tools.posthog_tools import posthog_generate_integration
from backend.tools.composio_tools import composio_linear_create_issue, composio_notion_create_page
from backend.tools.stripe_tools import create_product_with_payment_link


def build_technical_agent(**kwargs) -> Agent:
    return Agent(
        name="technical",
        role=(
            "You are a technical specialist. Your ONLY job is to build a complete working MVP.\n"
            "IGNORE any task wording that says 'scaffold', 'create Notion page', or similar. "
            "Always run the FULL workflow below regardless of how the task is phrased.\n\n"
            "MANDATORY WORKFLOW — never skip any step:\n"
            "1. obsidian_read(agent='technical', founder_id=<FOUNDER_ID>) — get research context\n"
            "2. github_create_repo(repo_name=<product-slug>, description=<desc>) — create repo, save repo_url\n"
            "3. run_mvp_loop(repo_url=<url>, goal=<full product description>, session_id=<SESSION>, context=<research notes>) — THIS IS MANDATORY. Builds full MVP in 4-6 rounds of Claude Code with commits each round. Do NOT skip this step.\n"
            "4. vercel_deploy_from_github(repo_url=<url>, root_directory='frontend') — deploy. If deployed=False, continue with repo_url only.\n"
            "5. obsidian_log — log repo_url and deploy_url\n"
            "6. done — return {repo_url, deploy_url, files_in_repo, rounds_run}\n\n"
            "run_mvp_loop writes ALL code — 6 rounds: frontend → backend → auth → polish → verify → final. "
            "Never call run_claude_in_repo instead of run_mvp_loop."
        ),
        tools={
            "github_create_repo": github_create_repo,
            "run_mvp_loop": run_mvp_loop,
            "run_claude_in_repo": run_claude_in_repo,
            "write_files_to_repo": write_files_to_repo,
            "vercel_deploy_from_github": vercel_deploy_from_github,
            "supabase_generate_schema": supabase_generate_schema,
            "supabase_create_project": supabase_create_project,
            "clerk_generate_integration": clerk_generate_integration,
            "posthog_generate_integration": posthog_generate_integration,
            "composio_linear_create_issue": composio_linear_create_issue,
            "composio_notion_create_page": composio_notion_create_page,
            "create_product_with_payment_link": create_product_with_payment_link,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
