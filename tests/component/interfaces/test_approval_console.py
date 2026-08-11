from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from customer_service.main import create_app


def _send(client: TestClient, conversation_id: str, message: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": message},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200
    return dict(response.json())


def _high_risk(client: TestClient) -> tuple[str, dict[str, Any]]:
    conversation_id = client.post("/api/v1/conversations").json()["conversation_id"]
    for message in (
        "我要退货，订单号是 ORD-HIGH-VALUE-001",
        "我不想要了",
        "商品未使用，包装完整",
    ):
        current = _send(client, conversation_id, message)
    assert current["agent_status"] == "waiting_approval"
    return conversation_id, dict(client.get("/api/v1/approvals").json()[0])


def test_high_risk_wait_is_visible_and_approval_resumes_same_controlled_workflow() -> None:
    client = TestClient(create_app())
    conversation_id, task = _high_risk(client)
    assert task["status"] == "pending"

    decided = client.post(
        f"/api/v1/approvals/{task['approval_id']}/decisions",
        json={
            "decision": "approve",
            "note": "人工复核通过。",
            "expected_version": task["version"],
        },
    )
    restored = client.get(f"/api/v1/conversations/{conversation_id}").json()

    assert decided.status_code == 200
    assert restored["agent_status"] == "completed"
    assert restored["service_case_id"]
    assert "批准" in restored["message"]


def test_approval_payload_rejects_actor_and_repeated_decision_has_no_second_write() -> None:
    client = TestClient(create_app())
    conversation_id, task = _high_risk(client)
    injected = client.post(
        f"/api/v1/approvals/{task['approval_id']}/decisions",
        json={
            "decision": "reject",
            "note": "复核。",
            "expected_version": task["version"],
            "actor_id": "ATTACKER",
        },
    )
    assert injected.status_code == 422

    payload = {
        "decision": "approve",
        "note": "批准。",
        "expected_version": task["version"],
    }
    assert (
        client.post(f"/api/v1/approvals/{task['approval_id']}/decisions", json=payload).status_code
        == 200
    )
    repeated = client.post(f"/api/v1/approvals/{task['approval_id']}/decisions", json=payload)
    restored = client.get(f"/api/v1/conversations/{conversation_id}").json()
    assert repeated.status_code == 409
    assert restored["service_case_id"]
