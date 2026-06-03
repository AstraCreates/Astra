"""Round-robin OpenRouter API key rotator.
Distributes concurrent LLM calls across multiple keys to avoid rate limits.
"""
import itertools
import threading
from backend.config import settings

_lock = threading.Lock()
_cycle = None


def _get_keys() -> list[str]:
    keys = []
    for k in [settings.openrouter_api_key, settings.openrouter_api_key_2, settings.openrouter_api_key_3]:
        if k and k.strip():
            keys.append(k.strip())
    return keys or [""]


def get_openrouter_key() -> str:
    """Return the next OpenRouter API key in round-robin order."""
    global _cycle
    with _lock:
        keys = _get_keys()
        if _cycle is None or True:  # always refresh in case keys changed
            _cycle = itertools.cycle(keys)
        return next(_cycle)
