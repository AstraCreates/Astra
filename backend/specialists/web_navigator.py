"""
Web Navigator specialist — vision-driven autonomous web agent.
Can sign up for services, grab API keys, fill forms, make purchases,
and complete any goal that requires navigating a real website.
"""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log


_ROLE = """You are Astra's Web Navigator — the agent that has real hands on the internet.

You can navigate any website, sign up for services, log in to dashboards, grab API keys,
fill out forms, and complete purchases. You use a real headless browser powered by
vision AI that takes screenshots and decides how to interact with each page.

## Your primary tool: run_web_task
Call run_web_task(task_type, service, goal, success_criteria, credentials) for any task that needs reliable
website execution. It is the bounded website operator and should be the default path for:
- Sign-up/login flows
- API key retrieval
- OAuth/connectors
- Basic dashboard provisioning
- Live QA of external websites

## Fallback tool: vision_browse
Use vision_browse(url, goal, credentials) only when the operator does not support the site yet or you need
exploratory browsing on an unusual page.

## Credentials
When the founder provides credentials (email, password, card details), pass them as the
`credentials` dict. The vision agent uses them automatically when it encounters login/payment forms.

## What you report back
Always report:
- What was accomplished
- Any API keys, tokens, or credentials extracted (exact values)
- The final URL
- Any errors or obstacles encountered

## When website tasks can't finish something
If the task requires human interaction (e.g., phone verification, CAPTCHA solving, 2FA app),
report exactly what is needed from the founder and provide the partial state and resume token.

## Persistence rules
- For sign-up goals, do not stop right after form submission; continue through email verification and into the dashboard.
- For API-key goals, do not stop at the homepage; navigate to Settings / Developers / API / Keys until you either extract the key or can clearly state what human step blocks it.
- If credentials are available, use them before asking for input.
- If a verification code or magic link is available in the test inbox, use it automatically.

## Common workflows
- **Grab API key**: navigate to service dashboard → find API section → copy key
- **Sign up**: go to signup page → fill form with provided credentials → verify email → return to dashboard
- **Purchase**: navigate to pricing → select plan → fill payment form → confirm
- **Connect service**: navigate to integration page → authorize → copy webhook/token

Always be specific about what you found. If you get an API key, output the full value."""


def build_web_navigator_agent(use_computer: bool = True, **model_kwargs) -> Agent:
    from backend.tools.web_navigator_tools import (
        vision_browse,
        check_email_for_verification,
        scan_page_for_keys,
    )
    from backend.tools.web_tasks import run_web_task

    async def _vision_browse_tool(
        url: str,
        goal: str,
        credentials: dict | None = None,
        max_steps: int = 30,
        founder_id: str = "",
        session_id: str = "",
    ) -> dict:
        """
        Autonomously navigate a website to achieve a goal using AI vision.
        Takes screenshots and uses Gemini Flash to decide each action.

        url: Starting URL (e.g. "https://platform.openai.com/api-keys")
        goal: Plain-English description of what to accomplish
              (e.g. "Sign in with email/password and copy the API key")
        credentials: Optional dict — {email, password, card_number, expiry, cvv, name, address, zip}
        max_steps: Max browser actions before giving up (default 30)
        """
        return await vision_browse(
            url=url,
            goal=goal,
            credentials=credentials or {},
            max_steps=max_steps,
            founder_id=founder_id,
            session_id=session_id,
        )

    async def _check_email_tool(service_name: str = "", timeout_seconds: int = 60) -> dict:
        """
        Check the Astra test email inbox for a verification code or magic link.
        Call this after triggering a sign-up or password-reset flow that sends an email.

        service_name: Name of service to filter by (e.g. "OpenAI", "Stripe") — optional
        timeout_seconds: How long to wait for the email (default 60s)
        Returns: {code, link, subject} or {error}
        """
        return await check_email_for_verification(
            service_name=service_name,
            timeout_seconds=timeout_seconds,
        )

    def _scan_keys_tool(text: str) -> dict:
        """
        Scan a block of text (e.g. pasted dashboard content) for API keys and tokens.
        Returns a dict of {key_type: key_value} for any found credentials.
        """
        return scan_page_for_keys(text)

    tools = {
        "run_web_task": run_web_task,
        "vision_browse": _vision_browse_tool,
        "check_email_for_verification": _check_email_tool,
        "scan_for_api_keys": _scan_keys_tool,
        "log_to_vault": obsidian_log,
    }

    return Agent(
        name="web_navigator",
        role=_ROLE,
        tools=tools,
        use_computer=use_computer,
        max_iterations=25,
        **model_kwargs,
    )
