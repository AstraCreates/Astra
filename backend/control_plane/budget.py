"""Wave 1 control plane: transactional budget reservations.

Bridges to the EXISTING legacy credits ledger (backend/credits/store.py) for
the actual balance -- per the plan's own Wave 1 note, "Legacy actual usage
can reconcile directly until LiteLLM lands." Reuses that module's real
per-founder threading.Lock (backend.credits.store._get_lock) for the
atomic check-and-reserve step, rather than inventing a second, uncoordinated
lock that a concurrent legacy backend.credits.store.deduct_credits() call
could race against.

Nothing in the running app calls this yet. Pure additive scaffolding.
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.control_plane.models import BudgetReservation
from backend.control_plane.repositories import BudgetReservationRepository

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 300


class BudgetExceededError(RuntimeError):
    """Raised when a reservation would push a founder's outstanding
    reservations + already-spent balance past their available credits."""


def usd_to_credits(usd: float, markup: float = 10.0) -> int:
    from backend.core.usage import CREDIT_USD

    return max(1, math.ceil(usd * max(1.0, markup) / CREDIT_USD))


class BudgetReservationService:
    """reserve / commit / release / expire, atomic per founder.

    Parent/child budget allocation from one shared account: reservations are
    tracked by founder_id (the SAME key backend.credits.store already uses),
    not by run_id -- a child run's reservations draw against and are summed
    with its parent's, because they share one founder-level credit balance.
    The BudgetReservation contract itself (matching PLAN.md's specified
    columns) has no founder_id column, so founder/credit bookkeeping lives
    in the repository layer as persisted reservation ledger metadata rather
    than in this service's process memory.
    """

    def __init__(self, repo: BudgetReservationRepository) -> None:
        self._repo = repo

    def _outstanding_credits_for_founder(self, founder_id: str) -> int:
        return self._repo.sum_reserved_credits(founder_id)

    def reserve(
        self,
        *,
        run_id: str,
        founder_id: str,
        estimated_max_usd: float,
        step_id: Optional[str] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        markup: float = 10.0,
    ) -> BudgetReservation:
        from backend.credits.store import _get_lock, _init_if_new, _load

        required_credits = usd_to_credits(estimated_max_usd, markup=markup)

        # The SAME lock backend.credits.store.deduct_credits() takes for this
        # founder -- this is what makes "parallel reservations cannot exceed
        # balance" actually true, not just true in the absence of concurrent
        # legacy spend. Reads the balance via the same lock-free primitives
        # get_balance() itself uses internally, rather than calling
        # get_balance() here -- that function acquires this exact lock via
        # _get_lock(founder_id) too, and it's a plain non-reentrant
        # threading.Lock, so calling it from inside this block would deadlock.
        with _get_lock(founder_id):
            balance = _init_if_new(founder_id, _load(founder_id))["balance"]
            outstanding = self._outstanding_credits_for_founder(founder_id)
            if balance - outstanding < required_credits:
                raise BudgetExceededError(
                    f"founder {founder_id!r}: balance={balance} outstanding={outstanding} "
                    f"required={required_credits} (requested ${estimated_max_usd:.4f})"
                )
            reservation = BudgetReservation(
                id=str(uuid.uuid4()),
                run_id=run_id,
                step_id=step_id,
                estimated_max_usd=estimated_max_usd,
                status="reserved",
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
            )
            return self._repo.reserve(
                reservation,
                founder_id=founder_id,
                reserved_credits=required_credits,
                markup=markup,
            )

    def commit(self, reservation_id: str, *, actual_usd: float, founder_id: Optional[str] = None) -> None:
        """Real spend happened. Reconciles against the legacy ledger directly
        (deduct_credits) since LiteLLM doesn't exist yet to do this itself.
        """
        if actual_usd < 0:
            raise ValueError(f"actual_usd must be non-negative, got {actual_usd}")

        from backend.credits.store import _get_lock, _init_if_new, _load

        reservation = self._repo.get(reservation_id)
        if reservation is None:
            raise KeyError(f"unknown reservation_id {reservation_id!r}")
        ledger = self._repo.get_ledger(reservation_id)
        resolved_founder = founder_id or (ledger.founder_id if ledger else None)
        if resolved_founder is None:
            raise ValueError(
                f"reservation {reservation_id!r} is missing founder context; "
                "pass founder_id explicitly for legacy compatibility"
            )
        if ledger and founder_id and founder_id != ledger.founder_id:
            raise ValueError(
                f"reservation {reservation_id!r} belongs to founder {ledger.founder_id!r}, "
                f"not {founder_id!r}"
            )

        markup = ledger.markup if ledger else 10.0
        actual_credits = usd_to_credits(actual_usd, markup=markup) if actual_usd > 0 else 0
        overspend_usd = max(0.0, actual_usd - reservation.estimated_max_usd)
        if overspend_usd > 0:
            logger.warning(
                "budget reservation %s overspend: actual_usd=%.6f exceeds estimated_max_usd=%.6f",
                reservation_id, actual_usd, reservation.estimated_max_usd,
            )

        billed_credits = 0
        unreconciled_credits = 0
        reconciliation_error: Optional[str] = None

        with _get_lock(resolved_founder):
            current = self._repo.get(reservation_id)
            if current is None:
                raise KeyError(f"unknown reservation_id {reservation_id!r}")
            if current.status == "committed":
                return
            if current.status != "reserved":
                raise ValueError(f"reservation {reservation_id!r} cannot commit from status {current.status!r}")

            balance = _init_if_new(resolved_founder, _load(resolved_founder))["balance"]
            outstanding_other = self._repo.sum_reserved_credits(
                resolved_founder,
                exclude_reservation_id=reservation_id,
            )
            available_credits = max(0, balance - outstanding_other)
            billed_credits = min(actual_credits, available_credits)
            unreconciled_credits = max(0, actual_credits - billed_credits)
            if billed_credits > 0:
                self._deduct_credits_locked(
                    resolved_founder,
                    billed_credits,
                    f"control-plane reservation {reservation_id} commit",
                    reservation.run_id,
                )
            if unreconciled_credits > 0:
                reconciliation_error = (
                    f"unreconciled actual spend: required={actual_credits} billed={billed_credits} "
                    f"outstanding_other={outstanding_other} balance={balance}"
                )
                logger.warning(
                    "budget reservation %s partially reconciled for founder %s: "
                    "required_credits=%d billed_credits=%d unreconciled_credits=%d",
                    reservation_id,
                    resolved_founder,
                    actual_credits,
                    billed_credits,
                    unreconciled_credits,
                )
            self._repo.commit(
                reservation_id,
                actual_usd,
                billed_credits=billed_credits,
                overspend_usd=overspend_usd,
                unreconciled_credits=unreconciled_credits,
                reconciliation_error=reconciliation_error,
            )

    def release(self, reservation_id: str) -> None:
        """No spend happened (call didn't fire, or ended cheaper than reserved
        and the caller reserves+commits separately) -- give the credits back."""
        self._repo.release(reservation_id)

    def expire_orphans(self, *, now: Optional[datetime] = None, has_terminal_receipt: "callable" = lambda reservation_id: False) -> list[str]:
        """Orphan reaper: an expired reservation with no active/terminal
        provider request is marked expired and audited (logged). has_terminal_receipt
        is a caller-supplied check against astra_action_receipts (or the fake
        equivalent) -- this module doesn't own that table, so it takes the
        check as a callable rather than importing a concrete repository."""
        now_iso = (now or datetime.now(timezone.utc)).isoformat()
        expired_ids: list[str] = []
        for reservation in self._repo.list_expired(now=now_iso):
            if has_terminal_receipt(reservation.id):
                # A provider call actually completed after the TTL elapsed
                # (e.g. a slow request) -- don't silently drop the spend,
                # leave it for an explicit commit.
                continue
            self._repo.expire(reservation.id)
            expired_ids.append(reservation.id)
            logger.warning(
                "budget reservation %s expired with no terminal provider request (run_id=%s, estimated_max_usd=%s)",
                reservation.id, reservation.run_id, reservation.estimated_max_usd,
            )
        return expired_ids

    @staticmethod
    def _deduct_credits_locked(founder_id: str, amount: int, description: str, session_id: str | None = None) -> None:
        from backend.credits.store import _init_if_new, _load, _make_tx, _save

        if amount <= 0:
            return
        data = _init_if_new(founder_id, _load(founder_id))
        if data["balance"] < amount:
            raise ValueError(
                f"insufficient credits: balance={data['balance']}, required={amount}"
            )
        data["balance"] -= amount
        data["total_used"] += amount
        data["transactions"].append(_make_tx("usage", amount, description, session_id))
        _save(data)
