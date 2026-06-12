"""Encrypted credential storage per founder on the persistent volume."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile

from backend.config import settings

_ENC_VERSION = 2
_STORE_DIR: Path | None = None


class CredentialsUnreadable(RuntimeError):
    """Credentials file is encrypted but cannot be decrypted with the current key.
    Raised to prevent silent overwrite of existing ciphertext with a fresh empty store."""


def _store_dir() -> Path:
    if _STORE_DIR is not None:
        return Path(_STORE_DIR)
    vault = os.environ.get("OBSIDIAN_VAULT") or settings.obsidian_vault
    return Path(vault).expanduser() / "credentials"


def _founder_path(founder_id: str) -> Path:
    store_dir = _store_dir()
    store_dir.mkdir(parents=True, exist_ok=True)
    safe = founder_id.replace("/", "_").replace("..", "_").replace(" ", "_")
    return store_dir / f"{safe}.json"


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _persist_env_key(key: str, value: str) -> None:
    env_path = Path(".env")
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True) if env_path.exists() else []
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}\n")
    _write_atomic(env_path, "".join(lines))


def _current_creds_key() -> str:
    return (getattr(settings, "astra_creds_key", "") or "").strip()


def _ensure_creds_key() -> str:
    key = _current_creds_key()
    if key:
        return key
    key = secrets.token_urlsafe(48)
    settings.astra_creds_key = key
    try:
        _persist_env_key("ASTRA_CREDS_KEY", key)
    except Exception:
        pass
    return key


def _require_creds_key() -> str:
    key = _current_creds_key()
    if key:
        return key
    raise RuntimeError("ASTRA_CREDS_KEY is required to read encrypted founder credentials")


def _openssl(args: list[str], payload: str, key: str) -> str:
    env = os.environ.copy()
    env["ASTRA_CREDS_PASSPHRASE"] = key
    proc = subprocess.run(
        ["openssl", *args, "-pass", "env:ASTRA_CREDS_PASSPHRASE"],
        input=payload,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "openssl failed")
    return proc.stdout


def _encrypt_payload(data: dict, key: str) -> dict:
    plaintext = json.dumps(data, separators=(",", ":"), sort_keys=True)
    ciphertext = _openssl(
        ["enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256", "-salt", "-a", "-A"],
        plaintext,
        key,
    ).strip()
    return {"version": _ENC_VERSION, "encrypted": True, "ciphertext": ciphertext}


def _decrypt_payload(blob: dict, key: str) -> dict:
    ciphertext = str(blob.get("ciphertext") or "")
    if not ciphertext:
        return {}
    plaintext = _openssl(
        ["enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256", "-salt", "-a", "-A"],
        ciphertext,
        key,
    )
    data = json.loads(plaintext or "{}")
    return data if isinstance(data, dict) else {}


def _read_file(path: Path) -> tuple[dict, bool]:
    if not path.exists():
        return {}, False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, False
    if isinstance(raw, dict) and raw.get("encrypted") is True:
        try:
            key = _require_creds_key()
            return _decrypt_payload(raw, key), False
        except Exception as exc:
            raise CredentialsUnreadable(
                f"Credentials file exists and is encrypted but cannot be decrypted "
                f"(wrong key or corrupted). Original error: {exc}"
            ) from exc
    return (raw if isinstance(raw, dict) else {}), True


def _rewrite_encrypted(path: Path, data: dict) -> None:
    envelope = _encrypt_payload(data, _ensure_creds_key())
    _write_atomic(path, json.dumps(envelope, indent=2))


def store_credentials(founder_id: str, service: str, creds: dict) -> None:
    path = _founder_path(founder_id)
    data, _ = _read_file(path)
    data[service] = creds
    _rewrite_encrypted(path, data)


def load_credentials(founder_id: str, service: str) -> dict | None:
    data = load_all_credentials(founder_id)
    return data.get(service)


def load_all_credentials(founder_id: str) -> dict:
    path = _founder_path(founder_id)
    data, was_plaintext = _read_file(path)
    if was_plaintext and data:
        _rewrite_encrypted(path, data)
    return data
