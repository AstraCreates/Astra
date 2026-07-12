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
    assert svc._repo.get(reservation.id).status == "released"
    # Released reservation no longer counts against the founder's outstanding total.
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


def test_commit_caps_billed_amount_at_the_reservation_ceiling():
    from backend.credits.store import get_balance

    svc = _service()
    before = get_balance("founder_4")
    reservation = svc.reserve(run_id="run_1", founder_id="founder_4", estimated_max_usd=1.0)

    # The call actually cost 5x what was reserved -- must not bill for 5x.
    svc.commit(reservation.id, actual_usd=5.0, founder_id="founder_4")

    after = get_balance("founder_4")
    spent_credits = before - after
    capped_expected = usd_to_credits(1.0)  # capped at estimated_max_usd, not 5.0
    assert spent_credits == capped_expected

    # The audit trail still records what actually happened, uncapped.
    stored = svc._repo.get(reservation.id)
    assert stored.actual_usd == 5.0
    assert stored.status == "committed"


def test_commit_under_reservation_bills_only_actual_spend():
    from backend.credits.store import get_balance

    svc = _service()
    before = get_balance("founder_5")
    reservation = svc.reserve(run_id="run_1", founder_id="founder_5", estimated_max_usd=2.0)
    svc.commit(reservation.id, actual_usd=0.5, founder_id="founder_5")

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
