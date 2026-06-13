from backend.tools.web_tasks.adapters.github import GitHubAdapter
from backend.tools.web_tasks.adapters.klaviyo import KlaviyoAdapter
from backend.tools.web_tasks.adapters.lemonsqueezy import LemonSqueezyAdapter
from backend.tools.web_tasks.adapters.printful import PrintfulAdapter
from backend.tools.web_tasks.adapters.sendgrid import SendGridAdapter
from backend.tools.web_tasks.adapters.square_sandbox import SquareSandboxAdapter
from backend.tools.web_tasks.adapters.supabase import SupabaseAdapter
from backend.tools.web_tasks.adapters.vercel import VercelAdapter
from backend.tools.web_tasks.adapters.yelp import YelpAdapter

ADAPTERS = [
    GitHubAdapter(),
    VercelAdapter(),
    SupabaseAdapter(),
    SendGridAdapter(),
    KlaviyoAdapter(),
    PrintfulAdapter(),
    YelpAdapter(),
    LemonSqueezyAdapter(),
    SquareSandboxAdapter(),
]


def resolve_adapter(service: str, task_type: str):
    normalized = (service or "").strip().lower()
    for adapter in ADAPTERS:
        if adapter.service == normalized and adapter.supports(task_type):
            return adapter
    return None
