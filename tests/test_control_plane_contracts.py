import threading
from datetime import datetime, timedelta, timezone

from backend.control_plane.backfill import backfill_runs, build_run_from_session_meta, supabase_run_writer
from backend.control_plane.action_executor import (
    ApprovalRequiredError,
    CancellationFenceError,
    ReceiptCollisionError,
    compute_action_hashes,
    execute_external_action,
    ExternalActionRequest,
)
from backend.control_plane.fakes import (
    FakeActionRepository,
    FakeActionReceiptRepository,
    FakeApprovalRequestRepository,
    FakeArtifactRepository,
    FakeBudgetReservationRepository,
    FakeRunEventRepository,
    FakeRunRepository,
    FakeRunStepRepository,
)
from backend.control_plane.models import (
    Action,
    ActionReceipt,
    ApprovalRequest,
    Artifact,
    BudgetReservation,
    BudgetReservationLedger,
    Run,
    RunStep,
)


def _run(**overrides) -> Run:
    defaults = dict(id="run_1", owner_id="f1", org_id="f1", goal="Investigate ICP")
    defaults.update(overrides)
    return Run(**defaults)


def test_every_model_round_trips_through_dump_and_validate():
    run = _run()
    assert Run.model_validate(run.model_dump()) == run

    step = RunStep(id="step_1", run_id="run_1", step_key="research", kind="agent")
    assert RunStep.model_validate(step.model_dump()) == step

    action = Action(id="a1", run_id="run_1", tool="deep_research", canonical_args_hash="h", idempotency_key="k1")
    assert Action.model_validate(action.model_dump()) == action

    approval = ApprovalRequest(id="ap1", run_id="run_1", gate_key="phase_gate_research", action_digest="d1")
    assert ApprovalRequest.model_validate(approval.model_dump()) == approval

    artifact = Artifact(id="art1", run_id="run_1", key="pitch_deck")
    assert Artifact.model_validate(artifact.model_dump()) == artifact

    reservation = BudgetReservation(id="res1", run_id="run_1", estimated_max_usd=1.5, expires_at=datetime.now(timezone.utc))
    assert BudgetReservation.model_validate(reservation.model_dump()) == reservation

    ledger = BudgetReservationLedger(reservation_id="res1", founder_id="f1", reserved_credits=100)
    assert BudgetReservationLedger.model_validate(ledger.model_dump()) == ledger


def test_model_defaults_are_not_shared_between_instances():
    first = Run(id="run_1", owner_id="f1", org_id="f1", goal="One")
    second = Run(id="run_2", owner_id="f2", org_id="f2", goal="Two")
    first.metadata["note"] = "kept local"
    assert second.metadata == {}

    first_artifact = Artifact(id="art1", run_id="run_1", key="deck")
    second_artifact = Artifact(id="art2", run_id="run_2", key="notes")
    first_artifact.metadata["version"] = 1
    assert second_artifact.metadata == {}


def test_fake_run_repository_create_get_update_status():
    repo = FakeRunRepository()
    repo.create(_run())
    assert repo.get("run_1").status == "queued"
    repo.update_status("run_1", "running")
    assert repo.get("run_1").status == "running"
    assert repo.get("does_not_exist") is None


def test_fake_run_step_repository_retry_creates_new_attempt_same_run_and_step_key():
    repo = FakeRunStepRepository()
    first = repo.create_attempt(RunStep(id="s1", run_id="run_1", step_key="build", kind="agent"))
    assert first.attempt_number == 1

    retry = repo.create_attempt(RunStep(id="s2", run_id="run_1", step_key="build", kind="agent"))
    assert retry.attempt_number == 2
    assert retry.run_id == first.run_id
    assert retry.step_key == first.step_key

    attempts = repo.list_attempts("run_1", "build")
    assert [a.attempt_number for a in attempts] == [1, 2]
    assert repo.get_latest_attempt("run_1", "build").id == "s2"

    # A different step_key under the same run starts its own attempt sequence.
    other = repo.create_attempt(RunStep(id="s3", run_id="run_1", step_key="deploy", kind="agent"))
    assert other.attempt_number == 1


def test_fake_run_event_repository_sequences_are_gapless_monotonic_and_thread_safe():
    repo = FakeRunEventRepository()
    sequences: list[int] = []
    lock = threading.Lock()

    def _append(i: int) -> None:
        seq = repo.append("run_1", "agent_start", {"i": i})
        with lock:
            sequences.append(seq)

    threads = [threading.Thread(target=_append, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(sequences) == list(range(50))  # gapless, no duplicates
    events = repo.list_since("run_1")
    assert len(events) == 50
    assert sorted(e.sequence for e in events) == list(range(50))


def test_fake_run_event_repository_sequences_independent_per_run():
    repo = FakeRunEventRepository()
    a1 = repo.append("run_a", "agent_start", {})
    b1 = repo.append("run_b", "agent_start", {})
    a2 = repo.append("run_a", "agent_done", {})
    assert (a1, b1, a2) == (0, 0, 1)


def test_fake_run_event_repository_list_since_filters_by_sequence():
    repo = FakeRunEventRepository()
    for i in range(5):
        repo.append("run_1", "tick", {"i": i})
    assert [e.sequence for e in repo.list_since("run_1", after_sequence=3)] == [3, 4]


def test_fake_action_repository_lookup_by_idempotency_key():
    repo = FakeActionRepository()
    action = Action(id="a1", run_id="run_1", tool="deploy", canonical_args_hash="h", idempotency_key="idem_1")
    repo.create(action)
    assert repo.get_by_idempotency_key("idem_1").id == "a1"
    assert repo.get_by_idempotency_key("missing") is None
    repo.update_status("a1", "succeeded")
    assert repo.get("a1").status == "succeeded"


def test_compute_action_hashes_are_stable_for_same_inputs():
    first = compute_action_hashes(
        run_id="run_1",
        step_id="step_1",
        action_id="action_1",
        tool="deploy",
        args={"b": 2, "a": 1},
        policy_version="v1",
    )
    second = compute_action_hashes(
        run_id="run_1",
        step_id="step_1",
        action_id="action_1",
        tool="deploy",
        args={"a": 1, "b": 2},
        policy_version="v1",
    )
    assert first == second


def test_fake_approval_request_repository_decide_records_decision():
    repo = FakeApprovalRequestRepository()
    repo.create(ApprovalRequest(id="ap1", run_id="run_1", gate_key="phase_gate_research", action_digest="d1"))
    pending = repo.get_pending_for_gate("run_1", "phase_gate_research")
    assert len(pending) == 1
    decided = repo.decide("ap1", "approved", decided_by="founder_1", note="looks good")
    assert decided.status == "approved"
    assert decided.decided_by == "founder_1"
    assert repo.get_pending_for_gate("run_1", "phase_gate_research") == []


def test_fake_approval_request_repository_consume_marks_request_consumed():
    repo = FakeApprovalRequestRepository()
    repo.create(ApprovalRequest(
        id="ap1",
        run_id="run_1",
        gate_key="phase_gate_research",
        action_digest="d1",
        policy_version="v1",
        status="approved",
    ))
    consumed = repo.consume("ap1", expected_action_digest="d1", expected_policy_version="v1")
    assert consumed.status == "consumed"
    assert consumed.consumed_at is not None


def test_fake_action_receipt_repository_round_trips_by_action_and_idempotency_key():
    repo = FakeActionReceiptRepository()
    receipt = repo.create(ActionReceipt(id="r1", action_id="a1", idempotency_key="idem_1", provider_result={"ok": True}))
    assert repo.get_by_action_id("a1") == receipt
    assert repo.get_by_idempotency_key("idem_1") == receipt
    repo.update_collision_status("r1", "detected")
    assert repo.get_by_action_id("a1").collision_status == "detected"


def test_fake_artifact_repository_upsert_replaces_by_key():
    repo = FakeArtifactRepository()
    repo.upsert(Artifact(id="art1", run_id="run_1", key="pitch_deck", uri="s3://v1"))
    repo.upsert(Artifact(id="art1", run_id="run_1", key="pitch_deck", uri="s3://v2"))
    artifacts = repo.list_for_run("run_1")
    assert len(artifacts) == 1
    assert artifacts[0].uri == "s3://v2"


def test_execute_external_action_consumes_approval_and_persists_receipt():
    action_repo = FakeActionRepository()
    approval_repo = FakeApprovalRequestRepository()
    receipt_repo = FakeActionReceiptRepository()
    approval_repo.create(ApprovalRequest(
        id="approval_1",
        run_id="run_1",
        step_id="step_1",
        gate_key="deploy_gate",
        action_digest="digest_1",
        policy_version="v1",
        status="approved",
    ))

    async def _effect(args, idempotency_key):
        return {"args": args, "idempotency_key": idempotency_key}

    result = __import__("asyncio").run(execute_external_action(
        ExternalActionRequest(
            run_id="run_1",
            step_id="step_1",
            tool="deploy",
            args={"target": "prod"},
            require_approval=True,
            approval_id="approval_1",
            approval_action_digest="digest_1",
        ),
        action_repo=action_repo,
        receipt_repo=receipt_repo,
        approval_repo=approval_repo,
        execute_effect=_effect,
    ))

    assert result.action.status == "succeeded"
    assert result.receipt.provider_result["args"] == {"target": "prod"}
    assert approval_repo.get("approval_1").status == "consumed"


def test_execute_external_action_replays_existing_receipt_without_reinvoking_effect():
    action_repo = FakeActionRepository()
    receipt_repo = FakeActionReceiptRepository()
    calls = {"count": 0}

    async def _effect(_args, _idempotency_key):
        calls["count"] += 1
        return {"ok": True}

    request = ExternalActionRequest(
        run_id="run_1",
        step_id="step_1",
        action_id="action_fixed",
        tool="deploy",
        args={"target": "prod"},
    )
    first = __import__("asyncio").run(execute_external_action(
        request,
        action_repo=action_repo,
        receipt_repo=receipt_repo,
        approval_repo=None,
        execute_effect=_effect,
    ))
    second = __import__("asyncio").run(execute_external_action(
        request,
        action_repo=action_repo,
        receipt_repo=receipt_repo,
        approval_repo=None,
        execute_effect=_effect,
    ))

    assert calls["count"] == 1
    assert first.replayed is False
    assert second.replayed is True
    assert second.receipt.id == first.receipt.id


def test_execute_external_action_fails_closed_for_missing_approval_or_cancellation():
    action_repo = FakeActionRepository()
    receipt_repo = FakeActionReceiptRepository()

    async def _effect(_args, _idempotency_key):
        return {"ok": True}

    try:
        __import__("asyncio").run(execute_external_action(
            ExternalActionRequest(
                run_id="run_1",
                step_id="step_1",
                tool="deploy",
                args={},
                require_approval=True,
            ),
            action_repo=action_repo,
            receipt_repo=receipt_repo,
            approval_repo=None,
            execute_effect=_effect,
        ))
        assert False, "expected ApprovalRequiredError"
    except ApprovalRequiredError:
        pass

    try:
        __import__("asyncio").run(execute_external_action(
            ExternalActionRequest(run_id="run_1", step_id="step_1", tool="deploy", args={}),
            action_repo=action_repo,
            receipt_repo=receipt_repo,
            approval_repo=None,
            execute_effect=_effect,
            is_cancelled=lambda _run_id: True,
        ))
        assert False, "expected CancellationFenceError"
    except CancellationFenceError:
        pass


def test_execute_external_action_does_not_consume_approval_after_cancellation():
    action_repo = FakeActionRepository()
    receipt_repo = FakeActionReceiptRepository()
    approval_repo = FakeApprovalRequestRepository()
    approval_repo.create(ApprovalRequest(id="ap_cancel", run_id="run_cancel", gate_key="phase_gate", action_digest="digest_cancel", status="approved"))

    async def _effect(_args, _idempotency_key):
        return {"ok": True}

    try:
        __import__("asyncio").run(execute_external_action(
            ExternalActionRequest(
                run_id="run_cancel",
                step_id="step_1",
                tool="deploy",
                args={},
                require_approval=True,
                approval_id="ap_cancel",
                approval_action_digest="digest_cancel",
            ),
            action_repo=action_repo,
            receipt_repo=receipt_repo,
            approval_repo=approval_repo,
            execute_effect=_effect,
            is_cancelled=lambda _run_id: True,
        ))
        assert False, "expected CancellationFenceError"
    except CancellationFenceError:
        pass

    approval = approval_repo.get("ap_cancel")
    assert approval is not None
    assert approval.status == "approved"


def test_execute_external_action_marks_receipt_collision():
    action_repo = FakeActionRepository()
    receipt_repo = FakeActionReceiptRepository()
    existing = receipt_repo.create(ActionReceipt(
        id="receipt_1",
        action_id="other_action",
        idempotency_key="shared",
        provider_result={"ok": True},
    ))

    async def _effect(_args, _idempotency_key):
        return {"ok": True}

    original = compute_action_hashes

    def _fixed_hashes(**_kwargs):
        canonical_args_hash, _ = original(
            run_id="run_1",
            step_id="step_1",
            action_id="action_1",
            tool="deploy",
            args={},
            policy_version="v1",
        )
        return canonical_args_hash, "shared"

    import backend.control_plane.action_executor as executor_mod

    saved = executor_mod.compute_action_hashes
    executor_mod.compute_action_hashes = _fixed_hashes
    try:
        try:
            __import__("asyncio").run(execute_external_action(
                ExternalActionRequest(run_id="run_1", step_id="step_1", action_id="action_1", tool="deploy", args={}),
                action_repo=action_repo,
                receipt_repo=receipt_repo,
                approval_repo=None,
                execute_effect=_effect,
            ))
            assert False, "expected ReceiptCollisionError"
        except ReceiptCollisionError:
            pass
    finally:
        executor_mod.compute_action_hashes = saved

    assert receipt_repo.get_by_action_id(existing.action_id).collision_status == "detected"


def test_fake_budget_reservation_repository_lifecycle_and_expiry_sweep():
    repo = FakeBudgetReservationRepository()
    now = datetime.now(timezone.utc)
    repo.reserve(
        BudgetReservation(id="r1", run_id="run_1", estimated_max_usd=1.0, expires_at=now - timedelta(minutes=1)),
        founder_id="founder_1",
        reserved_credits=100,
    )
    repo.reserve(
        BudgetReservation(id="r2", run_id="run_1", estimated_max_usd=2.0, expires_at=now + timedelta(hours=1)),
        founder_id="founder_1",
        reserved_credits=200,
    )

    expired = repo.list_expired(now=now.isoformat())
    assert [r.id for r in expired] == ["r1"]
    assert repo.sum_reserved_credits("founder_1") == 300

    repo.commit("r2", actual_usd=1.75, billed_credits=175, overspend_usd=0.25, unreconciled_credits=25)
    assert repo._by_id["r2"].status == "committed"
    assert repo._by_id["r2"].actual_usd == 1.75
    assert repo._ledger_by_id["r2"].billed_credits == 175
    assert repo._ledger_by_id["r2"].unreconciled_credits == 25

    repo.expire("r1")
    assert repo._by_id["r1"].status == "expired"
    # Expired reservations no longer show up in the expiry sweep or outstanding total.
    assert repo.list_expired(now=now.isoformat()) == []
    assert repo.sum_reserved_credits("founder_1") == 0


def test_backfill_maps_legacy_session_meta_to_run_contract():
    meta = {
        "session_id": "sess_abc",
        "founder_id": "founder_1",
        "goal": "Launch a B2B SaaS",
        "stack_id": "saas_mvp",
        "status": "done",
        "created_at": "2026-07-01T00:00:00Z",
        "completed_at": "2026-07-01T02:00:00Z",
        "workspace_id": "",
        "company_id": "founder_1",
        "chapter_id": "",
        "parent_session_id": "",
        "kind": "launch",
    }
    run = build_run_from_session_meta(meta)
    assert run.id == "sess_abc"
    assert run.owner_id == "founder_1"
    assert run.status == "succeeded"
    assert run.engine == "legacy"
    assert run.metadata["backfilled_from"] == "session_store"


def test_backfill_dry_run_scans_without_writing():
    runs = [
        Run(id="run_1", owner_id="founder_1", org_id="founder_1", goal="Goal one"),
        Run(id="run_2", owner_id="founder_2", org_id="founder_2", goal="Goal two"),
    ]
    written: list[str] = []

    result = backfill_runs(runs, dry_run=True, writer=lambda run: written.append(run.id))

    assert result == type(result)(scanned=2, written=0, dry_run=True)
    assert written == []


def test_backfill_apply_uses_writer():
    runs = [Run(id="run_1", owner_id="founder_1", org_id="founder_1", goal="Goal one")]
    written: list[str] = []

    result = backfill_runs(runs, dry_run=False, writer=lambda run: written.append(run.id))

    assert result == type(result)(scanned=1, written=1, dry_run=False)
    assert written == ["run_1"]


def test_supabase_run_writer_uses_run_repository_create(mocker):
    create = mocker.stub(name="create")
    repo = mocker.Mock()
    repo.create = create
    mocker.patch("backend.control_plane.supabase_repositories.SupabaseRunRepository", return_value=repo)
    writer = supabase_run_writer()
    run = Run(id="run_1", owner_id="founder_1", org_id="founder_1", goal="Goal one")
    writer(run)
    create.assert_called_once_with(run)
