from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from customer_service.agent_http.schemas import AgentMode
from customer_service.agent_http.service import IdempotencyError
from customer_service.infrastructure.config.settings import DeepSeekSettings
from customer_service.main import create_app
from customer_service.model_gateway.schemas import ModelResponse, ModelResultStatus


def _new(client: TestClient, mode: str = "fake") -> dict[str, Any]:
    response = client.post("/api/v1/conversations", json={"mode": mode})
    assert response.status_code == 200
    return dict(response.json())


def _send(
    client: TestClient, conversation_id: str, message: str, *, key: str | None = None
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": message},
        headers={"Idempotency-Key": key or str(uuid4())},
    )
    assert response.status_code == 200
    return dict(response.json())


def test_fake_api_is_default_deterministic_and_returns_only_public_contract() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v1/conversations").json()
    key = str(uuid4())
    first = _send(client, created["conversation_id"], "查询订单 ORD-NORMAL-001", key=key)
    replay = _send(client, created["conversation_id"], "查询订单 ORD-NORMAL-001", key=key)

    assert first == replay
    assert first["requested_mode"] == first["effective_mode"] == "fake"
    assert first["agent_status"] == "completed"
    assert first["model_status"] == "succeeded"
    assert "ORD-NORMAL-001" in first["message"]
    forbidden = {
        "api_key",
        "permit",
        "evidence_id",
        "workflow_id",
        "checkpoint_id",
        "gate_reasons",
        "tool_parameters",
    }
    assert forbidden.isdisjoint(str(first).lower())


def test_modes_and_unconfigured_deepseek_are_explicit_without_silent_fallback(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    settings = DeepSeekSettings(deepseek_api_key=None, deepseek_model=None)
    from customer_service.agent_http.composition import build_agent_application

    app = create_app()
    app.state.agent_application = build_agent_application(deepseek_settings=settings)
    client = TestClient(app)
    modes = client.get("/api/v1/agent/modes").json()
    deepseek = next(item for item in modes["modes"] if item["id"] == "deepseek")
    requested = client.post("/api/v1/conversations", json={"mode": "deepseek"})

    assert modes["default_mode"] == "fake"
    assert deepseek == {
        "id": "deepseek",
        "configured": False,
        "selectable": False,
        "reason_code": "AGENT_MODE_NOT_CONFIGURED",
    }
    assert requested.status_code == 409
    assert requested.json()["detail"]["code"] == "AGENT_MODE_NOT_CONFIGURED"


def test_public_payload_cannot_inject_controlled_context_and_idempotency_is_required() -> None:
    client = TestClient(create_app())
    conversation_id = _new(client)["conversation_id"]
    injected = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": "退货", "user_id": "USR-DEMO-002", "evidence": []},
        headers={"Idempotency-Key": str(uuid4())},
    )
    missing = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"message": "退货"}
    )
    invalid = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": "退货"},
        headers={"Idempotency-Key": "not-a-uuid"},
    )

    assert injected.status_code == 422
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "IDEMPOTENCY_KEY_INVALID"
    assert invalid.status_code == 400


def test_policy_question_exposes_whitelisted_traceable_citation() -> None:
    client = TestClient(create_app())
    conversation_id = _new(client)["conversation_id"]
    result = _send(client, conversation_id, "我想了解退货政策")

    assert result["agent_status"] == "completed"
    assert result["citations"]
    assert set(result["citations"][0]) == {"policy_id", "title", "source"}
    assert result["citations"][0]["source"].startswith("synthetic://")


def test_idempotency_key_conflict_is_safe() -> None:
    client = TestClient(create_app())
    conversation_id = _new(client)["conversation_id"]
    key = str(uuid4())
    _send(client, conversation_id, "查询订单 ORD-NORMAL-001", key=key)
    conflict = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message": "查询订单 ORD-QUALITY-001"},
        headers={"Idempotency-Key": key},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"


def test_same_key_is_globally_bound_and_cross_conversation_replay_conflicts() -> None:
    client = TestClient(create_app())
    first = _new(client)["conversation_id"]
    second = _new(client)["conversation_id"]
    key = str(uuid4())
    assert (
        client.post(
            f"/api/v1/conversations/{first}/messages",
            json={"message": "查询订单 ORD-NORMAL-001"},
            headers={"Idempotency-Key": key},
        ).status_code
        == 200
    )
    replay = client.post(
        f"/api/v1/conversations/{second}/messages",
        json={"message": "查询订单 ORD-NORMAL-001"},
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"


def test_concurrent_same_key_enters_controlled_execution_only_once(
    monkeypatch: Any,
) -> None:
    app = create_app()
    service = app.state.agent_application.conversations
    conversation_id = service.create(AgentMode.FAKE).conversation_id
    key = str(uuid4())
    entered = Event()
    release = Event()
    calls = 0
    original = service._execute

    def blocked(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_execute", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.send, conversation_id, "查询订单 ORD-NORMAL-001", key)
        assert entered.wait(timeout=5)
        second = pool.submit(service.send, conversation_id, "查询订单 ORD-NORMAL-001", key)
        with pytest.raises(IdempotencyError, match="IDEMPOTENCY_REQUEST_IN_PROGRESS"):
            second.result(timeout=5)
        release.set()
        completed = first.result(timeout=5)

    replay = service.send(conversation_id, "查询订单 ORD-NORMAL-001", key)
    assert calls == 1
    assert replay == completed
    assert len(replay.messages) == 3


def test_unexpected_write_outcome_is_saved_and_never_reexecuted(monkeypatch: Any) -> None:
    app = create_app()
    service = app.state.agent_application.conversations
    conversation_id = service.create(AgentMode.FAKE).conversation_id
    key = str(uuid4())
    calls = 0

    def unknown(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise RuntimeError("secret provider detail")

    monkeypatch.setattr(service, "_execute", unknown)
    first = service.send(conversation_id, "我要退货", key)
    second = service.send(conversation_id, "我要退货", key)
    assert calls == 1
    assert second == first
    assert first.reason_code == "WRITE_OUTCOME_UNKNOWN"
    assert "secret" not in first.message


def test_explicit_deepseek_provider_failure_stops_safely_without_fake_fallback(
    monkeypatch: Any,
) -> None:
    from customer_service.agent_http.composition import build_agent_application
    from customer_service.model_gateway.deepseek import DeepSeekModelGateway

    def unavailable(self: DeepSeekModelGateway, request: Any) -> ModelResponse:
        return ModelResponse(
            status=ModelResultStatus.PROVIDER_FAILURE,
            task=request.task,
            output=None,
            error_code="DEEPSEEK_PROVIDER_UNAVAILABLE",
            message="provider unavailable",
        )

    monkeypatch.setattr(DeepSeekModelGateway, "generate", unavailable)
    settings = DeepSeekSettings(
        deepseek_api_key=SecretStr("test-only-key"),
        deepseek_model="deepseek-test",
    )
    app = create_app()
    app.state.agent_application = build_agent_application(deepseek_settings=settings)
    client = TestClient(app)
    created = _new(client, "deepseek")
    result = _send(client, created["conversation_id"], "查询订单 ORD-NORMAL-001")

    assert result["requested_mode"] == result["effective_mode"] == "deepseek"
    assert result["agent_status"] == "failed_safe"
    assert result["model_status"] == "unavailable"
    assert result["can_start_fake_conversation"] is True
    assert "test-only-key" not in str(result)
