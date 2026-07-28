from typing import cast

import pytest
from fastapi.testclient import TestClient

from customer_service.interfaces.api.routes.approvals import console
from customer_service.main import create_app


def _high_risk_task(client: TestClient) -> tuple[str, dict[str, object]]:
    console.reset_for_test()
    conversation = client.post("/api/v1/conversations").json()["conversation_id"]
    for message in (
        "我要退货，订单号是 ORD-HIGH-VALUE-001",
        "我不想要了",
        "商品未使用，包装完整",
    ):
        client.post(f"/api/v1/conversations/{conversation}/messages", json={"message": message})
    task = cast(dict[str, object], client.get("/api/v1/approvals").json()[-1])
    return conversation, task


def test_approval_console_lists_a_trusted_high_risk_task_and_decides_once() -> None:
    client = TestClient(create_app())
    _high_risk_task(client)
    listed = client.get("/api/v1/approvals")

    assert listed.status_code == 200
    task = listed.json()[0]
    assert task["status"] == "pending"
    assert task["eligibility"]["requires_human_approval"] is True
    assert task["risk_reasons"]
    assert task["policy_citations"]
    assert "decided_by" not in task or task["decided_by"] is None

    decided = client.post(
        f"/api/v1/approvals/{task['approval_id']}/decisions",
        json={
            "decision": "reject",
            "note": "高风险事实已复核。",
            "expected_version": task["version"],
        },
    )
    repeated = client.post(
        f"/api/v1/approvals/{task['approval_id']}/decisions",
        json={"decision": "approve", "note": "重复提交。", "expected_version": task["version"]},
    )

    assert decided.status_code == 200
    assert decided.json()["status"] == "rejected"
    assert decided.json()["decided_by"] == "USR-AGENT-001"
    assert repeated.status_code == 409


def test_approval_decision_payload_rejects_actor_or_business_facts() -> None:
    client = TestClient(create_app())
    _, task = _high_risk_task(client)

    response = client.post(
        f"/api/v1/approvals/{task['approval_id']}/decisions",
        json={
            "decision": "reject",
            "note": "审核。",
            "expected_version": task["version"],
            "actor_id": "USR-ADMIN-001",
        },
    )

    assert response.status_code == 422


def test_approved_high_risk_task_updates_the_same_consumer_conversation() -> None:
    client = TestClient(create_app())
    conversation, task = _high_risk_task(client)

    approved = client.post(
        f"/api/v1/approvals/{task['approval_id']}/decisions",
        json={"decision": "approve", "note": "批准。", "expected_version": task["version"]},
    )
    restored = client.get(f"/api/v1/conversations/{conversation}")

    assert approved.status_code == 200
    assert restored.status_code == 200
    assert restored.json()["status"] == "completed"
    assert restored.json()["service_case_id"]

    repeated = client.post(
        f"/api/v1/approvals/{task['approval_id']}/decisions",
        json={"decision": "approve", "note": "重复批准。", "expected_version": task["version"]},
    )
    refreshed = client.get(f"/api/v1/conversations/{conversation}").json()
    assert repeated.status_code == 409
    assert refreshed["service_case_id"] == restored.json()["service_case_id"]


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    (("adjust", "needs_clarification"), ("reject", "rejected")),
)
def test_adjust_and_reject_are_reflected_in_the_consumer_without_a_case(
    decision: str, expected_status: str
) -> None:
    client = TestClient(create_app())
    conversation, task = _high_risk_task(client)

    decided = client.post(
        f"/api/v1/approvals/{task['approval_id']}/decisions",
        json={
            "decision": decision,
            "note": "人工复核。",
            "recommendation": "请补充凭证。" if decision == "adjust" else None,
            "expected_version": task["version"],
        },
    )
    restored = client.get(f"/api/v1/conversations/{conversation}")

    assert decided.status_code == 200
    assert restored.status_code == 200
    assert restored.json()["status"] == expected_status
    assert restored.json()["service_case_id"] is None


def test_stale_version_does_not_decide_or_resume_the_consumer_workflow() -> None:
    client = TestClient(create_app())
    conversation, task = _high_risk_task(client)

    stale = client.post(
        f"/api/v1/approvals/{task['approval_id']}/decisions",
        json={
            "decision": "approve",
            "note": "陈旧提交。",
            "expected_version": cast(int, task["version"]) + 1,
        },
    )
    approval = client.get("/api/v1/approvals").json()[0]
    restored = client.get(f"/api/v1/conversations/{conversation}").json()

    assert stale.status_code == 409
    assert approval["status"] == "pending"
    assert restored["status"] == "requires_approval"
    assert restored["service_case_id"] is None
