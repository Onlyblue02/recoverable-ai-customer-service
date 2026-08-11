from customer_service.agent_acceptance.runner import run_fixed_acceptance, stable_projection


def test_fake_runner_is_repeatable_and_preserves_failures() -> None:
    first = run_fixed_acceptance(executor=lambda _: 0)
    second = run_fixed_acceptance(executor=lambda _: 0)

    assert first["passed"] == first["total"] == 31
    assert first["failed"] == 0
    assert stable_projection(first) == stable_projection(second)
    assert first["preserved_failures"]
    assert all(failure.get("improvement_suggestion") for failure in first["preserved_failures"])


def test_failure_is_not_relabelled_and_identifies_the_failed_stage() -> None:
    failed_node = (
        "tests/unit/agent_tools/test_execution.py::"
        "test_failed_order_lookup_never_issues_public_evidence"
    )
    report = run_fixed_acceptance(executor=lambda nodeid: 1 if nodeid == failed_node else 0)
    failed = [case for case in report["cases"] if not case["passed"]]

    assert report["failed"] == 1 and len(failed) == 1
    assert failed[0]["status"] == "failed"
    assert failed[0]["stage"] == "tool"
    assert failed[0]["failure_reason"] == "TOOL_ASSERTION_FAILED"
    assert failed[0]["actual"]["pytest_exit_code"] == 1
    assert failed[0]["expected"]["security_outcome"] == "NO_PUBLIC_EVIDENCE"
    assert failed[0]["actual"]["security_outcome"] == "ASSERTION_FAILED"
