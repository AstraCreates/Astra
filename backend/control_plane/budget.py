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
import threading
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
    columns) has no founder_id column, so that mapping lives here in the
    service's own in-memory index, not on the persisted record.
    """

    def __init__(self, repo: BudgetReservationRepository) -> None:
        self._repo = repo
        self._index_lock = threading.Lock()
        # reservation_id -> (founder_id, credits) for every still-outstanding
        # ('reserved') reservation. Removed on commit/release/expire.
        self._outstanding: dict[str, tuple[str, int]] = {}

    def _outstanding_credits_for_founder(self, founder_id: str) -> int:
        with self._index_lock:
            return sum(credits for fid, credits in self._outstanding.values() if fid == founder_id)

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
            reservation = self._repo.reserve(reservation)
            with self._index_lock:
                self._outstanding[reservation.id] = (founder_id, required_credits)
            return reservation

    def commit(self, reservation_id: str, *, actual_usd: float, founder_id: Optional[str] = None) -> None:
        """Real spend happened. Reconciles against the legacy ledger directly
        (deduct_credits) since LiteLLM doesn't exist yet to do this itself.

        "One oversized provider call cannot bypass its reserved maximum":
        billed spend is capped at the reservation's own estimated_max_usd,
        never the raw actual_usd. A call that genuinely cost more than its
        reservation is an overshoot to investigate (logged loudly), not a
        bigger bill this reservation gets to authorize on its own -- that
        would make the reservation meaningless as a ceiling. The excess
        needs its own separate reservation/incident, not a silent bypass.
        """
        reservation = self._repo.get(reservation_id)
        if reservation is None:
            raise KeyError(f"unknown reservation_id {reservation_id!r}")

        billed_usd = actual_usd
        if actual_usd > reservation.estimated_max_usd:
            logger.warning(
                "budget reservation %s overshoot: actual_usd=%.6f exceeds estimated_max_usd=%.6f — "
                "billing capped at the reservation, excess needs its own reservation/incident",
                reservation_id, actual_usd, reservation.estimated_max_usd,
            )
            billed_usd = reservation.estimated_max_usd

        self._repo.commit(reservation_id, actual_usd)
        with self._index_lock:
            entry = self._outstanding.pop(reservation_id, None)
        resolved_founder = founder_id or (entry[0] if entry else None)
        if resolved_founder and billed_usd > 0:
            from backend.credits.store import deduct_credits

            credits = usd_to_credits(billed_usd)
            deduct_credits(resolved_founder, credits, f"control-plane reservation {reservation_id} commit", "")

    def release(self, reservation_id: str) -> None:
        """No spend happened (call didn't fire, or ended cheaper than reserved
        and the caller reserves+commits separately) -- give the credits back."""
        self._repo.release(reservation_id)
        with self._index_lock:
            self._outstanding.pop(reservation_id, None)

    def expire_orphans(self, *, now: Optional[datetime] = None, has_terminal_receipt: "callable" = lambda reservation_id: False) -> list[str]:
        """Orphan reaper: an expired reservation with no active/terminal
        provider request is released and audited (logged). has_terminal_receipt
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
            self.release(reservation.id)
            expired_ids.append(reservation.id)
            logger.warning(
                "budget reservation %s expired with no terminal provider request — released (run_id=%s, estimated_max_usd=%s)",
                reservation.id, reservation.run_id, reservation.estimated_max_usd,
            )
        return expired_ids
