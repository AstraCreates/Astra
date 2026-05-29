"""PostHog analytics tools — setup, event tracking code gen, funnel analysis."""
import logging
import requests
from backend.config import settings

logger = logging.getLogger(__name__)
_API = "https://app.posthog.com/api"


def _llm_generate(prompt: str, model: str = "fast") -> str:
    try:
        from backend.tools._llm import generate
        return generate(prompt, model=model)
    except Exception as e:
        logger.warning("LLM posthog generation failed: %s", e)
        return ""


def _llm_key_events(product_description: str) -> list[str]:
    """Use LLM to generate product-specific PostHog key events from a product description."""
    prompt = (
        f"You are a product analytics expert. Given this product description:\n\n"
        f"{product_description}\n\n"
        "List exactly 7 PostHog key events to track for this product. "
        "Use snake_case, be specific to the product's core actions (not generic platform internals). "
        "Always include user_signed_up and upgrade_clicked. "
        "Output ONLY the event names, one per line, no explanations, no bullets, no numbers."
    )
    raw = _llm_generate(prompt)
    if not raw:
        return ["user_signed_up", "onboarding_completed", "feature_used", "upgrade_clicked", "session_started"]
    events = [line.strip().lower().replace(" ", "_").replace("-", "_")
              for line in raw.splitlines() if line.strip()]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique = []
    for e in events:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    return unique[:8]


def _llm_events_code(key_events: list[str]) -> str:
    """Generate posthog.capture() snippet for a list of key events."""
    lines = ["// Track key events", "import { usePostHog } from 'posthog-js/react';", "const posthog = usePostHog();", ""]
    for event in key_events[:4]:
        lines.append(f"posthog.capture('{event}');")
    return "\n".join(lines)


def _detect_app_type(product_description: str) -> str:
    """Guess app_type from product description for event spec lookup."""
    desc = product_description.lower()
    if any(w in desc for w in ["marketplace", "listing", "buyer", "seller", "vendor", "two-sided"]):
        return "marketplace"
    return "saas"


def _headers():
    key = getattr(settings, "posthog_api_key", "")
    return {"Authorization": f"Bearer {key}"} if key else {}


def posthog_generate_integration(app_name: str, framework: str = "nextjs", product_description: str = "") -> dict:
    """
    Generate PostHog analytics integration for a user's app.
    framework: nextjs | react | node | python
    product_description: optional — used to generate product-specific key events via LLM.
    """
    if framework == "nextjs":
        # Generate product-specific key events
        if product_description:
            key_events = _llm_key_events(product_description)
        else:
            key_events = [
                "user_signed_up", "user_logged_in", "onboarding_completed",
                "feature_used", "upgrade_clicked", "session_started",
            ]

        events_code = _llm_events_code(key_events)

        return {
            "app": app_name,
            "install": "npm install posthog-js posthog-node",
            "env_vars": {
                "NEXT_PUBLIC_POSTHOG_KEY": "phc_your_key_here",
                "NEXT_PUBLIC_POSTHOG_HOST": "https://app.posthog.com",
            },
            "provider": (
                "// app/providers.tsx\n"
                "'use client'\n"
                "import posthog from 'posthog-js';\n"
                "import { PostHogProvider } from 'posthog-js/react';\n"
                "import { useEffect } from 'react';\n\n"
                "export function PHProvider({ children }: { children: React.ReactNode }) {\n"
                "  useEffect(() => {\n"
                "    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {\n"
                "      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,\n"
                "      capture_pageview: false,\n"
                "    });\n"
                "  }, []);\n"
                "  return <PostHogProvider client={posthog}>{children}</PostHogProvider>;\n"
                "}"
            ),
            "pageview": (
                "// app/posthog-pageview.tsx\n"
                "'use client'\n"
                "import { usePathname, useSearchParams } from 'next/navigation';\n"
                "import { usePostHog } from 'posthog-js/react';\n"
                "import { useEffect } from 'react';\n\n"
                "export function PostHogPageview() {\n"
                "  const pathname = usePathname();\n"
                "  const posthog = usePostHog();\n"
                "  useEffect(() => { posthog.capture('$pageview'); }, [pathname]);\n"
                "  return null;\n"
                "}"
            ),
            "events": events_code,
            "key_events": key_events,
        }
    elif framework == "python":
        return {
            "install": "pip install posthog",
            "setup": (
                "from posthog import Posthog\n"
                "posthog = Posthog(project_api_key='phc_...', host='https://app.posthog.com')\n\n"
                "posthog.capture('user_id', 'event_name', {'property': 'value'})"
            ),
        }
    return {"error": f"Unsupported framework: {framework}"}


def posthog_create_key_events_spec(app_name: str, app_type: str = "saas", product_description: str = "") -> dict:
    """
    Generate a PostHog event tracking specification for a SaaS or marketplace app.
    product_description: optional — when provided, generates product-specific events via LLM
                         and auto-detects app_type if app_type is still "saas".
    """
    # Auto-detect app_type from product description when possible
    if product_description and app_type == "saas":
        app_type = _detect_app_type(product_description)

    if product_description:
        # Use LLM to generate product-specific events with properties
        prompt = (
            f"You are a product analytics expert. Product: {app_name}.\n"
            f"Description: {product_description}\n\n"
            "Generate a PostHog event tracking spec. List 6-8 events specific to this product's core actions.\n"
            "For each event output exactly:\n"
            "EVENT: <snake_case_event_name>\n"
            "PROPERTIES: <prop1>, <prop2>, <prop3>\n\n"
            "Always include user_signed_up (properties: plan, source, referrer) and upgrade_clicked (properties: from_page, current_plan).\n"
            "Do NOT include Astra-internal events (goal_submitted, agent_run_started, agent_run_completed).\n"
            "Output only the EVENT/PROPERTIES lines, nothing else."
        )
        raw = _llm_generate(prompt)
        llm_events: list[dict] = []
        current_event: str | None = None
        for line in (raw or "").splitlines():
            line = line.strip()
            if line.upper().startswith("EVENT:"):
                current_event = line.split(":", 1)[1].strip().lower().replace(" ", "_").replace("-", "_")
            elif line.upper().startswith("PROPERTIES:") and current_event:
                props = [p.strip() for p in line.split(":", 1)[1].split(",") if p.strip()]
                llm_events.append({"event": current_event, "properties": props})
                current_event = None

        if llm_events:
            # Derive funnel steps from generated events
            signed_up = next((e["event"] for e in llm_events if "signed_up" in e["event"]), "user_signed_up")
            onboarded = next((e["event"] for e in llm_events if "onboard" in e["event"]), None)
            core_action = next((e["event"] for e in llm_events if e["event"] not in {signed_up, onboarded} and "upgrade" not in e["event"]), None)
            upgrade_clicked = next((e["event"] for e in llm_events if "upgrade" in e["event"] and "click" in e["event"]), "upgrade_clicked")
            upgrade_done = next((e["event"] for e in llm_events if "upgrade" in e["event"] and "click" not in e["event"]), None)

            activation_steps = [s for s in [signed_up, onboarded, core_action] if s]
            conversion_steps = [s for s in [upgrade_clicked, upgrade_done] if s]

            return {
                "app": app_name,
                "app_type": app_type,
                "events": llm_events,
                "funnels": [
                    {"name": "Activation", "steps": activation_steps},
                    {"name": "Conversion", "steps": conversion_steps},
                ],
                "dashboard_url": "https://app.posthog.com",
            }

    # Fallback static specs when no product description is provided
    events_by_type = {
        "saas": [
            {"event": "user_signed_up", "properties": ["plan", "source", "referrer"]},
            {"event": "onboarding_completed", "properties": ["steps_completed", "time_to_complete"]},
            {"event": "feature_used", "properties": ["feature_name", "session_id"]},
            {"event": "upgrade_viewed", "properties": ["current_plan", "from_page"]},
            {"event": "upgrade_completed", "properties": ["from_plan", "to_plan", "mrr"]},
            {"event": "session_started", "properties": ["source"]},
            {"event": "churn_risk", "properties": ["days_inactive", "last_feature_used"]},
        ],
        "marketplace": [
            {"event": "user_signed_up", "properties": ["role", "source", "referrer"]},
            {"event": "listing_viewed", "properties": ["listing_id", "category"]},
            {"event": "listing_created", "properties": ["category", "price"]},
            {"event": "purchase_started", "properties": ["item_id", "price"]},
            {"event": "purchase_completed", "properties": ["item_id", "price", "payment_method"]},
            {"event": "review_submitted", "properties": ["rating", "item_id"]},
            {"event": "upgrade_clicked", "properties": ["from_page", "current_plan"]},
        ],
    }
    spec_events = events_by_type.get(app_type, events_by_type["saas"])
    return {
        "app": app_name,
        "app_type": app_type,
        "events": spec_events,
        "funnels": [
            {"name": "Activation", "steps": ["user_signed_up", "onboarding_completed", "feature_used"]},
            {"name": "Conversion", "steps": ["upgrade_viewed", "upgrade_completed"]},
        ],
        "dashboard_url": "https://app.posthog.com",
    }


def posthog_get_insights(event_name: str, days: int = 30) -> dict:
    """Fetch event count from PostHog API for a given event."""
    if not _headers():
        return {"note": "POSTHOG_API_KEY not set", "event": event_name}
    try:
        project_id = getattr(settings, "posthog_project_id", "")
        resp = requests.get(
            f"{_API}/projects/{project_id}/events/",
            headers=_headers(),
            params={"event": event_name, "limit": 100},
            timeout=10,
        )
        data = resp.json()
        return {"event": event_name, "count": len(data.get("results", [])), "days": days}
    except Exception as e:
        return {"error": str(e)}
