import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.control_plane.budget import BudgetExceededError, BudgetReservationService, usd_to_credits
from backend.control_plane.fakes import FakeBudgetReservationRepository


@pytest.fixture(autouse=True)
def _isolated_credits_vault(tmp_path: Path, monkeypatch):
    # backend.credits.store reads/writes real files under OBSIDIAN_VAULT --
    # sandbox every test so they can't touch (or race on) the real vault.
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    yield


def _service() -> BudgetReservationService:
    return BudgetReservationService(FakeBudgetReservationRepository())


def test_reserve_succeeds_within_balance_and_deducts_nothing_yet():
    from backend.credits.store import get_balance

    svc = _service()
    before = get_balance("founder_1")
    reservation = svc.reserve(run_id="run_1", founder_id="founder_1", estimated_max_usd=1.0)
    assert reservation.status == "reserved"
    # A reservation alone doesn't spend anything -- only commit() does.
    assert get_balance("founder_1") == before


def test_reserve_raises_when_it_would_exceed_balance():
    svc = _service()
    # 1 credit = $0.005, 10x markup -> $1 of estimated cost = 2000 credits.
    # Starting balance is 5,000,000 credits (~$2500 at cost, before markup).
    with pytest.raises(BudgetExceededError):
        svc.reserve(run_id="run_1", founder_id="founder_1", estimated_max_usd=10_000_000.0)


def test_parallel_reservations_cannot_exceed_balance():
    from backend.credits.store import get_balance

    svc = _service()
    balance = get_balance("founder_10")
    # usd_to_credits(usd) == ceil(usd * 2000) at the default 10x markup /
    # $0.005 credit price. Size each reservation at exactly half the balance
    # in credits, converted back to USD, so exactly 2 of 5 concurrent
    # reservations fit and the other 3 cannot, regardless of thread order.
    credits_per_reservation = balance // 2
    per_reservation_usd = credits_per_reservation / 2000
    assert usd_to_credits(per_reservation_usd) == credits_per_reservation  # sanity: exact, no rounding slop
    results: list[str] = []
    lock = threading.Lock()

    def _try_reserve():
        try:
            svc.reserve(run_id="run_1", founder_id="founder_10", estimated_max_usd=per_reservation_usd)
            with lock:
                results.append("ok")
        except BudgetExceededError:
            with lock:
                results.append("exceeded")

    threads = [threading.Thread(target=_try_reserve) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 2
    assert results.count("exceeded") == 3


def test_expire_orphans_releases_reservations_past_ttl_with_no_terminal_receipt():
    svc = _service()
    reservation = svc.reserve(run_id="run_1", founder_id="founder_2", estimated_max_usd=0.5, ttl_seconds=1)

    expired = svc.expire_orphans(now=datetime.now(timezone.utc) + timedelta(seconds=5))
    assert expired == [reservation.id]
    assert svc._repo.get(reservation.id).status == "expired"
    # Expired reservation no longer counts against the founder's outstanding total.
    assert svc._outstanding_credits_for_founder("founder_2") == 0


def test_expire_orphans_skips_reservations_with_a_terminal_receipt():
    svc = _service()
    reservation = svc.reserve(run_id="run_1", founder_id="founder_3", estimated_max_usd=0.5, ttl_seconds=1)

    expired = svc.expire_orphans(
        now=datetime.now(timezone.utc) + timedelta(seconds=5),
        has_terminal_receipt=lambda rid: rid == reservation.id,
    )
    assert expired == []
    # Still outstanding -- a slow-but-real provider call shouldn't have its
    # reservation silently dropped out from under it.
    assert svc._outstanding_credits_for_founder("founder_3") > 0


def test_commit_reconciles_actual_overspend_when_balance_allows():
    from backend.credits.store import get_balance

    svc = _service()
    before = get_balance("founder_4")
    reservation = svc.reserve(run_id="run_1", founder_id="founder_4", estimated_max_usd=1.0)

    # The call actually cost 5x what was reserved and the founder has enough
    # balance to reconcile the full amount.
    svc.commit(reservation.id, actual_usd=5.0)

    after = get_balance("founder_4")
    spent_credits = before - after
    assert spent_credits == usd_to_credits(5.0)

    # The audit trail records the actual spend and the fact it overshot.
    stored = svc._repo.get(reservation.id)
    assert stored.actual_usd == 5.0
    assert stored.status == "committed"
    ledger = svc._repo.get_ledger(reservation.id)
    assert ledger.overspend_usd == 4.0
    assert ledger.unreconciled_credits == 0


def test_commit_under_reservation_bills_only_actual_spend():
    from backend.credits.store import get_balance

    svc = _service()
    before = get_balance("founder_5")
    reservation = svc.reserve(run_id="run_1", founder_id="founder_5", estimated_max_usd=2.0)
    svc.commit(reservation.id, actual_usd=0.5)

    after = get_balance("founder_5")
    assert before - after == usd_to_credits(0.5)


def test_child_run_reservations_share_the_parent_founders_balance():
    svc = _service()
    # Parent and child sessions share one founder-level credit balance --
    # child reservations count against the SAME outstanding total.
    svc.reserve(run_id="parent_run", founder_id="founder_6", estimated_max_usd=1.0)
    svc.reserve(run_id="child_run", founder_id="founder_6", estimated_max_usd=1.0)

    outstanding = svc._outstanding_credits_for_founder("founder_6")
    assert outstanding == usd_to_credits(1.0) * 2

    # And a third reservation that would push past the shared balance fails,
    # regardless of which run_id it's attributed to.
    with pytest.raises(BudgetExceededError):
        svc.reserve(run_id="grandchild_run", founder_id="founder_6", estimated_max_usd=10_000_000.0)


def test_release_frees_the_outstanding_reservation_without_billing():
    from backend.credits.store import get_balance

    svc = _service()
    before = get_balance("founder_7")
    reservation = svc.reserve(run_id="run_1", founder_id="founder_7", estimated_max_usd=1.0)
    svc.release(reservation.id)

    assert svc._outstanding_credits_for_founder("founder_7") == 0
    assert get_balance("founder_7") == before  # never actually spent
    assert svc._repo.get(reservation.id).status == "released"


def test_commit_uses_repository_state_after_service_restart():
    from backend.credits.store import get_balance

    repo = FakeBudgetReservationRepository()
    first = BudgetReservationService(repo)
    reservation = first.reserve(run_id="run_1", founder_id="founder_8", estimated_max_usd=1.25)

    second = BudgetReservationService(repo)
    assert second._outstanding_credits_for_founder("founder_8") == usd_to_credits(1.25)

    before = get_balance("founder_8")
    second.commit(reservation.id, actual_usd=1.0)
    after = get_balance("founder_8")

    assert before - after == usd_to_credits(1.0)
    assert repo.get(reservation.id).status == "committed"


def test_commit_records_unreconciled_overspend_when_other_reservations_hold_capacity():
    from backend.credits.store import get_balance

    svc = _service()
    balance = get_balance("founder_9")
    credits_per_reservation = balance // 2
    per_reservation_usd = credits_per_reservation / 2000

    first = svc.reserve(run_id="run_1", founder_id="founder_9", estimated_max_usd=per_reservation_usd)
    svc.reserve(run_id="run_2", founder_id="founder_9", estimated_max_usd=per_reservation_usd)

    before = get_balance("founder_9")
    svc.commit(first.id, actual_usd=per_reservation_usd * 2)
    after = get_balance("founder_9")

    assert before - after == credits_per_reservation
    ledger = svc._repo.get_ledger(first.id)
    assert ledger.billed_credits == credits_per_reservation
    assert ledger.unreconciled_credits == credits_per_reservation
    assert ledger.reconciliation_error is not None
