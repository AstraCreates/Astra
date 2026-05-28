"""Credential storage per founder, stored in local .credentials/ directory."""
import json
import os
from pathlib import Path

_STORE_DIR = Path(__file__).parent.parent.parent / ".credentials"


def _founder_path(founder_id: str) -> Path:
    _STORE_DIR.mkdir(exist_ok=True)
    safe = founder_id.replace("/", "_").replace("..", "_").replace(" ", "_")
    return _STORE_DIR / f"{safe}.json"


def store_credentials(founder_id: str, service: str, creds: dict) -> None:
    path = _founder_path(founder_id)
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception:
            pass
    data[service] = creds
    path.write_text(json.dumps(data, indent=2))


def load_credentials(founder_id: str, service: str) -> dict | None:
    path = _founder_path(founder_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data.get(service)
    except Exception:
        return None


def load_all_credentials(founder_id: str) -> dict:
    path = _founder_path(founder_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}
