from typing import cast

from fastapi.testclient import TestClient

from customer_service.main import create_app


def _new_conversation(client: TestClient) -> str:
    response = client.post("/api/v1/conversations")
    assert response.status_code == 200
    body = cast(dict[str, object], response.json())
    assert body["status"] == "collecting_information"
    return cast(str, body["conversation_id"])


def _send(client: TestClient, conversation_id: str, message: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"message": message}
    )
    assert response.status_code == 200
    return cast(dict[str, object], response.json())


def test_consumer_conversation_completes_the_real_standard_return_workflow_once() -> None:
    client = TestClient(create_app())
    conversation_id = _new_conversation(client)

    first = _send(client, conversation_id, "我要退货，订单号是 ORD-NORMAL-001")
    second = _send(client, conversation_id, "我不想要了")
    completed = _send(client, conversation_id, "商品未使用，包装完整")
    repeated = _send(client, conversation_id, "商品未使用，包装完整")

    assert first["status"] == "collecting_information"
    assert second["status"] == "collecting_information"
    assert completed["status"] == "completed"
    assert completed["service_case_id"]
    citations = completed["citations"]
    assert isinstance(citations, list) and citations
    citation = citations[0]
    assert isinstance(citation, dict)
    assert set(citation) == {"policy_id", "title", "source"}
    assert citation["policy_id"] == "POL-ACTIVE-STANDARD-001"
    assert repeated["status"] == "completed"
    assert repeated["service_case_id"] == completed["service_case_id"]


def test_missing_or_unauthorized_orders_never_complete_or_leak_facts() -> None:
    client = TestClient(create_app())
    for order_id in ("ORD-NOT-FOUND-001", "ORD-OTHER-USER-001"):
        conversation_id = _new_conversation(client)
        _send(client, conversation_id, f"我要退货，订单号是 {order_id}")
        _send(client, conversation_id, "我不想要了")
        result = _send(client, conversation_id, "商品未使用，包装完整")

        assert result["status"] == "order_unavailable"
        assert result["service_case_id"] is None
        assert order_id not in str(result["message"])
        assert "89.00" not in str(result["message"])


def test_message_payload_rejects_identity_or_business_facts() -> None:
    client = TestClient(create_app())
    conversation_id = _new_conversation(client)

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": "我要退货", "current_user_id": "USR-DEMO-002"},
    )

    assert response.status_code == 422


def test_policy_question_returns_a_real_current_policy_citation() -> None:
    client = TestClient(create_app())
    conversation_id = _new_conversation(client)

    result = _send(client, conversation_id, "我想了解退货政策")

    assert result["status"] == "collecting_information"
    citations = result["citations"]
    assert isinstance(citations, list) and citations
    assert citations[0]["policy_id"] == "POL-ACTIVE-STANDARD-001"
    assert citations[0]["source"] == "synthetic://racs/policies/standard-return/v1"


def test_order_query_returns_only_authorized_whitelist_or_a_non_enumerating_failure() -> None:
    client = TestClient(create_app())
    own_conversation = _new_conversation(client)
    own = _send(client, own_conversation, "查询订单 ORD-NORMAL-001")

    assert own["status"] == "collecting_information"
    assert own["order"] == {
        "order_id": "ORD-NORMAL-001",
        "status": "delivered",
        "total_amount": "129.00",
        "currency": "CNY",
    }

    failures = []
    for order_id in ("ORD-NOT-FOUND-001", "ORD-OTHER-USER-001"):
        result = _send(client, _new_conversation(client), f"查询订单 {order_id}")
        failures.append(result)
        assert result["status"] == "order_unavailable"
        assert result["order"] is None
        assert result["service_case_id"] is None
        assert order_id not in str(result["message"])
    assert all(
        result["status"] == failures[0]["status"]
        and result["message"] == failures[0]["message"]
        and set(result) == set(failures[0])
        for result in failures
    )


def test_get_conversation_restores_current_snapshot_and_unknown_session_is_not_found() -> None:
    client = TestClient(create_app())
    conversation_id = _new_conversation(client)
    _send(client, conversation_id, "我要退货，订单号是 ORD-NORMAL-001")

    restored = client.get(f"/api/v1/conversations/{conversation_id}")
    unknown = client.get("/api/v1/conversations/not-a-session")

    assert restored.status_code == 200
    body = restored.json()
    assert len(body["messages"]) == 3
    assert body["messages"][-1]["role"] == "assistant"
    assert unknown.status_code == 404
