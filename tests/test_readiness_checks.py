from backend.readiness.checks import ReadinessCheck, make_check, registered_check, run_registered_checks


def test_make_check_preserves_legacy_default_shape():
    check = make_check("probe", True, "Probe passed.", {"count": 1})

    assert check == {
        "key": "probe",
        "ok": True,
        "message": "Probe passed.",
        "details": {"count": 1},
    }


def test_make_check_can_preserve_empty_missing_field():
    check = make_check(
        "deploy_probe",
        False,
        "Probe failed.",
        {"configured": False},
        missing=[],
        include_empty_missing=True,
    )

    assert check == {
        "key": "deploy_probe",
        "ok": False,
        "message": "Probe failed.",
        "details": {"configured": False},
        "missing": [],
    }


def test_registered_checks_run_in_requested_order():
    @registered_check("__test_ready")
    def ready_check():
        return ReadinessCheck("__test_ready", True, "ready")

    @registered_check("__test_missing")
    def missing_check():
        return make_check("__test_missing", False, "missing", {}, missing=["TOKEN"])

    checks = run_registered_checks(["__test_missing", "__test_ready"])

    assert [check["key"] for check in checks] == ["__test_missing", "__test_ready"]
    assert checks[0]["missing"] == ["TOKEN"]
    assert checks[1] == {
        "key": "__test_ready",
        "ok": True,
        "message": "ready",
        "details": {},
    }
