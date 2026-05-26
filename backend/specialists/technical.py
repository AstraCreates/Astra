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


def build_technical_agent(**kwargs) -> Agent:
    return Agent(
        name="technical",
        role=(
            "You are a technical specialist. Build a complete working MVP and push it to GitHub.\n\n"
            "WORKFLOW — exact sequence:\n"
            "1. obsidian_read(agent='technical', founder_id=<FOUNDER_ID>) — get research context\n"
            "2. github_create_repo(repo_name=<slug>, description=<desc>) — create repo, save repo_url\n"
            "3. run_mvp_loop(repo_url=<url>, goal=<product description>, session_id=<SESSION>, context=<research notes from step 1>) — builds full MVP in 4-6 rounds of Claude Code, commits each round\n"
            "4. vercel_deploy_from_github(repo_url=<url>, founder_id=<FOUNDER_ID>) — deploy\n"
            "5. obsidian_log — log repo_url and deploy_url\n"
            "6. done — return {repo_url, deploy_url, files_in_repo, rounds_run}\n\n"
            "run_mvp_loop handles ALL code writing — it loops Claude Code until frontend, backend, auth, "
            "and DB are complete. Do NOT call run_claude_in_repo separately; run_mvp_loop does it all. "
            "Only call write_files_to_repo if you need to patch a specific file after the loop."
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
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
