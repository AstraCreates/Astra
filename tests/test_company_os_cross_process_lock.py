"""Confirmed production incident: Company OS's event-log append was protected
only by json_file_lock's process-local threading.RLock. Under
WEB_CONCURRENCY=4 (multiple real backend worker PROCESSES, not just threads),
that lock provides zero real mutual exclusion -- each process gets its own
independent lock object. Two workers racing on the same company's event log
both read the same last_sequence, both appended, and corrupted the sequence
with a duplicate number. Every future read of that company then 500'd forever
("Company OS event sequence is not contiguous"), and the new dashboard polls
this endpoint every 3s with no backoff -- hammering the backend continuously,
which is almost certainly what surfaced as "the VPS randomly hangs".

This test reproduces the race with real OS processes (not threads -- a
threading.Lock still works fine within one process; the bug only appears
across process boundaries) and confirms cross_process_file_lock's flock-based
fix prevents it.
"""
import multiprocessing
import sys

import pytest


def _hammer_squad_update(root, company_id, squad_id, n, error_queue):
    # Re-import inside the child process (spawn start method, no fork-inherited state).
    from backend import company_os
    for _ in range(n):
        try:
            company_os.update_squad(company_id, squad_id, root=root, lifecycle="working", state="working")
        except Exception as exc:
            error_queue.put(str(exc))


@pytest.mark.timeout(60)
def test_concurrent_worker_processes_do_not_corrupt_event_sequence(tmp_path):
    from backend import company_os

    root = tmp_path
    company_os.create_company_os("acme", "founder1", "Acme", root=root)
    company_os.create_initiative("acme", "Launch", root=root, initiative_id="init1")
    company_os.create_squad("acme", "init1", "Squad", root=root, squad_id="squad_1")

    ctx = multiprocessing.get_context("spawn" if sys.platform == "darwin" else "fork")
    error_queue = ctx.Queue()
    procs = [
        ctx.Process(target=_hammer_squad_update, args=(root, "acme", "squad_1", 15, error_queue))
        for _ in range(4)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)

    errors = []
    while not error_queue.empty():
        errors.append(error_queue.get())
    assert not errors, f"concurrent writers hit errors: {errors[:3]}"

    # The real assertion: replay must not raise "event sequence is not contiguous".
    state = company_os.get_company_os("acme", root=root)
    assert state is not None
    assert len(state["squads"]) == 1
