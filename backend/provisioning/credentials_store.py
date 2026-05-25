"""Encrypted credential storage per founder, stored in local .credentials/ directory."""
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet

_KEY_ENV = "ASTRA_CREDS_KEY"
_STORE_DIR = Path(".credentials")


def _get_fernet() -> Fernet:
    key = os.environ.get(_KEY_ENV)
    if not key:
        key = Fernet.generate_key().decode()
        os.environ[_KEY_ENV] = key
    return Fernet(key.encode() if isinstance(key, str) else key)


def _founder_path(founder_id: str) -> Path:
    _STORE_DIR.mkdir(exist_ok=True)
    safe = founder_id.replace("/", "_").replace("..", "_").replace(" ", "_")
    return _STORE_DIR / f"{safe}.json"


def store_credentials(founder_id: str, service: str, creds: dict) -> None:
    fernet = _get_fernet()
    path = _founder_path(founder_id)
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception:
            pass
    data[service] = fernet.encrypt(json.dumps(creds).encode()).decode()
    path.write_text(json.dumps(data))


def load_credentials(founder_id: str, service: str) -> dict | None:
    path = _founder_path(founder_id)
    if not path.exists():
        return None
    fernet = _get_fernet()
    try:
        data = json.loads(path.read_text())
        if service not in data:
            return None
        return json.loads(fernet.decrypt(data[service].encode()))
    except Exception:
        return None


def load_all_credentials(founder_id: str) -> dict:
    path = _founder_path(founder_id)
    if not path.exists():
        return {}
    fernet = _get_fernet()
    data = json.loads(path.read_text())
    result = {}
    for service, encrypted in data.items():
        try:
            result[service] = json.loads(fernet.decrypt(encrypted.encode()))
        except Exception:
            pass
    return result
