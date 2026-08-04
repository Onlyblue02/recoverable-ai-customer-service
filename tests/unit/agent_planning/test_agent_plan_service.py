from collections.abc import Mapping
from typing import Any

from customer_service.agent_planning.service import AgentPlanOutcome, AgentPlanService
from customer_service.agent_runtime.executor import ControlledAgentExecutor
from customer_service.agent_runtime.schemas import (
    AgentEventType,
    AgentReasonCode,
    AgentState,
    AgentStatus,
)
from customer_service.model_gateway.fake import FakeModelGateway


def _planning(executor: ControlledAgentExecutor) -> AgentState:
    state = executor.receive_turn(conversation_id="CONV-1", turn_id="TURN-1", user_id="USER-1")
    state = executor.apply_event(state, AgentEventType.USER_MESSAGE)
    return executor.apply_event(state, AgentEventType.MODEL_RESULT)


def _service(payload: Mapping[str, Any]) -> tuple[ControlledAgentExecutor, AgentPlanService]:
    executor = ControlledAgentExecutor()
    return executor, AgentPlanService(
        executor=executor, model_gateway=FakeModelGateway({"TURN-1": payload})
    )


def test_validated_read_only_plan_advances_only_to_validating_plan() -> None:
    executor, service = _service(
        {
            "schema_version": "agent-plan-v1",
            "intent": "order_query",
            "requested_capability": "order.get_authorized",
            "extracted_parameters": {"order_id": "ORD-1"},
            "clarification_fields": [],
            "uncertainty_reason": None,
        }
    )
    result = service.propose(_planning(executor), text="查订单", prompt_version="t603-v1")

    assert result.outcome is AgentPlanOutcome.READY_FOR_VALIDATION
    assert result.state.status is AgentStatus.VALIDATING_PLAN
    assert result.state.reason_code is AgentReasonCode.PLAN_ACCEPTED
    assert result.plan is not None
    assert "查订单" not in result.audit.model_dump_json()


def test_uncertain_plan_routes_to_clarifying_without_tool_execution() -> None:
    executor, service = _service(
        {
            "schema_version": "agent-plan-v1",
            "intent": "unknown",
            "requested_capability": "clarify",
            "extracted_parameters": {},
            "clarification_fields": ["order_id"],
            "uncertainty_reason": "ambiguous_intent",
        }
    )
    result = service.propose(_planning(executor), text="帮我处理", prompt_version="t603-v1")

    assert result.outcome is AgentPlanOutcome.CLARIFY
    assert result.state.status is AgentStatus.CLARIFYING
    assert result.state.executed_steps == ()


def test_invalid_schema_and_unauthorized_capability_safely_stop() -> None:
    invalid: dict[str, Any] = {
        "schema_version": "agent-plan-v1",
        "intent": "order_query",
        "requested_capability": "order.write",
        "extracted_parameters": {},
        "clarification_fields": [],
        "uncertainty_reason": None,
    }
    executor, service = _service(invalid)
    result = service.propose(_planning(executor), text="修改订单", prompt_version="t603-v1")
    assert result.outcome is AgentPlanOutcome.FAILED_SAFE
    assert result.state.reason_code is AgentReasonCode.PLAN_MODEL_INVALID

    policy_invalid = {**invalid, "requested_capability": "policy.lookup"}
    executor, service = _service(policy_invalid)
    result = service.propose(_planning(executor), text="查订单", prompt_version="t603-v1")
    assert result.state.status is AgentStatus.FAILED_SAFE
    assert result.state.reason_code is AgentReasonCode.PLAN_POLICY_VIOLATION


def test_fake_plan_is_deterministic() -> None:
    executor = ControlledAgentExecutor()
    service = AgentPlanService(executor=executor, model_gateway=FakeModelGateway())
    first = service.propose(_planning(executor), text="x", prompt_version="t603-v1")
    second = service.propose(_planning(executor), text="x", prompt_version="t603-v1")
    assert first == second
