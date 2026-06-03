"""Credits store for Astra.

Per-user credit ledger stored at:
  $OBSIDIAN_VAULT/credits/{founder_id}.json

Thread-safe with a per-founder threading.Lock().
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_INITIAL_CREDITS = 10_000_000_000_000  # 10T — effectively unlimited for beta
_MAX_TRANSACTIONS = 100

# Per-user locks to avoid cross-user contention
_locks: dict[str, threading.Lock] = {}
_locks_mu = threading.Lock()


def _get_lock(founder_id: str) -> threading.Lock:
    with _locks_mu:
        if founder_id not in _locks:
            _locks[founder_id] = threading.Lock()
        return _locks[founder_id]


# ── Paths ──────────────────────────────────────────────────────────────────────

def _credits_dir() -> Path:
    vault = os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")
    d = Path(vault) / "credits"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _credits_path(founder_id: str) -> Path:
    return _credits_dir() / f"{founder_id}.json"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _default(founder_id: str) -> dict[str, Any]:
    now = _now()
    return {
        "founder_id": founder_id,
        "balance": 0,
        "total_granted": 0,
        "total_purchased": 0,
        "total_used": 0,
        "created_at": now,
        "updated_at": now,
        "transactions": [],
    }


def _load(founder_id: str) -> dict[str, Any]:
    """Load credits file. Returns default structure if not found or corrupt.
    Does NOT acquire the lock — must be called under the founder's lock."""
    p = _credits_path(founder_id)
    if not p.exists():
        return _default(founder_id)
    try:
        return json.loads(p.read_text())
    except Exception:
        return _default(founder_id)


def _save(data: dict[str, Any]) -> None:
    """Persist the credits record, trimming to last 100 transactions.
    Must be called under the founder's lock."""
    data["updated_at"] = _now()
    if len(data.get("transactions", [])) > _MAX_TRANSACTIONS:
        data["transactions"] = data["transactions"][-_MAX_TRANSACTIONS:]
    _credits_path(data["founder_id"]).write_text(json.dumps(data, indent=2))


def _make_tx(
    tx_type: str,
    amount: int,
    description: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:16],
        "type": tx_type,
        "amount": amount,
        "description": description,
        "session_id": session_id or "",
        "ts": _now(),
    }


def _init_if_new(founder_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """If this is a brand-new record (balance 0 and no transactions), apply welcome grant.
    Must be called under the founder's lock."""
    if data["balance"] == 0 and not data["transactions"]:
        data["balance"] = _INITIAL_CREDITS
        data["total_granted"] = _INITIAL_CREDITS
        data["transactions"].append(
            _make_tx("grant", _INITIAL_CREDITS, "Welcome bonus — 10 free credits")
        )
        _save(data)
    return data


# ── Public API ─────────────────────────────────────────────────────────────────

def get_credits(founder_id: str) -> dict[str, Any]:
    """Return the credits record for the founder, creating with 10 free credits if new."""
    lock = _get_lock(founder_id)
    with lock:
        data = _load(founder_id)
        data = _init_if_new(founder_id, data)
        return data


def add_credits(
    founder_id: str,
    amount: int,
    type: str,
    description: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Add credits to the founder's balance.

    Args:
        founder_id: The founder's user ID.
        amount: Positive integer number of credits to add.
        type: One of 'grant', 'purchase', or 'refund'.
        description: Human-readable description for the transaction log.
        session_id: Optional session ID to associate with the transaction.

    Returns:
        Updated credits dict.
    """
    if amount <= 0:
        raise ValueError(f"amount must be positive, got {amount}")
    if type not in ("grant", "purchase", "refund"):
        raise ValueError(f"type must be 'grant', 'purchase', or 'refund', got {type!r}")

    lock = _get_lock(founder_id)
    with lock:
        data = _load(founder_id)
        data = _init_if_new(founder_id, data)
        data["balance"] += amount
        if type == "grant":
            data["total_granted"] += amount
        elif type == "purchase":
            data["total_purchased"] += amount
        # refund only affects balance (not counters)
        data["transactions"].append(_make_tx(type, amount, description, session_id))
        _save(data)
        return data


def deduct_credits(
    founder_id: str,
    amount: int,
    description: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Deduct credits from the balance.

    Args:
        founder_id: The founder's user ID.
        amount: Positive integer number of credits to deduct.
        description: Human-readable description for the transaction log.
        session_id: Optional session ID to associate with the transaction.

    Returns:
        Updated credits dict.

    Raises:
        ValueError: If the founder has insufficient credits.
    """
    if amount <= 0:
        raise ValueError(f"amount must be positive, got {amount}")

    lock = _get_lock(founder_id)
    with lock:
        data = _load(founder_id)
        data = _init_if_new(founder_id, data)
        if data["balance"] < amount:
            # Auto-refill: users have unlimited credits (top up by 10x the required amount)
            refill = max(amount * 10, _INITIAL_CREDITS)
            data["balance"] += refill
            data["total_granted"] += refill
            data["transactions"].append(_make_tx("grant", refill, "Auto-refill — unlimited credits", session_id))
        data["balance"] -= amount
        data["total_used"] += amount
        data["transactions"].append(_make_tx("usage", amount, description, session_id))
        _save(data)
        return data


def check_credits(founder_id: str, required: int = 10) -> bool:
    """Return True if the founder has at least `required` credits."""
    lock = _get_lock(founder_id)
    with lock:
        data = _load(founder_id)
        data = _init_if_new(founder_id, data)
        return data["balance"] >= required


def get_balance(founder_id: str) -> int:
    """Return the current credit balance for the founder."""
    lock = _get_lock(founder_id)
    with lock:
        data = _load(founder_id)
        data = _init_if_new(founder_id, data)
        return data["balance"]
