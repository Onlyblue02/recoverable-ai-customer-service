import pytest
from pydantic import ValidationError

from customer_service.agent_runtime.executor import ControlledAgentExecutor
from customer_service.agent_runtime.schemas import (
    AgentEventType,
    AgentExecutionPolicy,
    AgentReasonCode,
    AgentState,
    AgentStatus,
)
from customer_service.agent_tools.registry import ToolRegistry
from customer_service.agent_tools.schemas import (
    ParameterSource,
    PlanValidationContext,
    ToolEffect,
    ToolId,
    TrustedParameter,
)
from customer_service.agent_tools.validator import ToolPlanOutcome, ToolPlanValidator
from customer_service.model_gateway.schemas import AgentPlanCandidate, ReturnFieldCandidate


def _state(executor: ControlledAgentExecutor) -> AgentState:
    state = executor.receive_turn(conversation_id="CONV-1", turn_id="TURN-1", user_id="USER-1")
    state = executor.apply_event(state, AgentEventType.USER_MESSAGE)
    state = executor.apply_event(state, AgentEventType.MODEL_RESULT)
    return executor.accept_validated_model_plan(state)


def _plan(capability: str = "order.get_authorized") -> AgentPlanCandidate:
    return AgentPlanCandidate.model_validate(
        {
            "schema_version": "agent-plan-v1",
            "intent": "order_query",
            "requested_capability": capability,
            "extracted_parameters": {"order_id": "ORD-1"},
            "clarification_fields": [],
            "uncertainty_reason": None,
        }
    )


def _context(*, calls: tuple[str, ...] = ()) -> PlanValidationContext:
    return PlanValidationContext(
        authorized_user_id="USER-1",
        trusted_parameters=(
            TrustedParameter(
                name="order_id", value="ORD-1", source=ParameterSource.CONFIRMED_FIELD
            ),
        ),
        executed_call_keys=calls,
    )


def test_static_registry_classifies_without_executable_implementations() -> None:
    registry = ToolRegistry()
    policy = registry.get("policy.lookup")
    evaluate = registry.get("return.evaluate")
    high_risk = registry.get("high_risk.resume")
    assert policy is not None and policy.effect is ToolEffect.READ_ONLY
    assert evaluate is not None and evaluate.effect is ToolEffect.CONTROLLED_BUSINESS_REQUEST
    assert high_risk is not None and high_risk.effect is ToolEffect.MODEL_FORBIDDEN_HIGH_RISK
    assert not hasattr(policy, "execute")


def test_valid_plan_compiles_but_does_not_execute_a_tool() -> None:
    executor = ControlledAgentExecutor()
    result = ToolPlanValidator(executor=executor).validate(_state(executor), _plan(), _context())
    assert result.outcome is ToolPlanOutcome.VALIDATED
    assert result.state.status is AgentStatus.VALIDATING_PLAN
    assert result.step is not None
    assert result.step.tool_id is ToolId.ORDER_GET_AUTHORIZED
    assert result.state.executed_steps == ()


def test_unknown_forbidden_wrong_state_and_missing_data_do_not_proceed() -> None:
    executor = ControlledAgentExecutor()
    validator = ToolPlanValidator(executor=executor)
    unknown = _plan().model_copy(update={"requested_capability": "unknown.tool"})
    assert (
        validator.validate(_state(executor), unknown, _context()).reason_code
        is AgentReasonCode.TOOL_NOT_REGISTERED
    )
    forbidden = _plan().model_copy(update={"requested_capability": "high_risk.resume"})
    assert (
        validator.validate(_state(executor), forbidden, _context()).reason_code
        is AgentReasonCode.TOOL_FORBIDDEN
    )
    wrong_state = executor.receive_turn(
        conversation_id="CONV-1", turn_id="TURN-1", user_id="USER-1"
    )
    assert (
        validator.validate(wrong_state, _plan(), _context()).reason_code
        is AgentReasonCode.TOOL_STATE_NOT_ALLOWED
    )
    incomplete = _plan().model_copy(
        update={"extracted_parameters": ReturnFieldCandidate(order_id=None)}
    )
    clarified = validator.validate(_state(executor), incomplete, _context())
    assert clarified.outcome is ToolPlanOutcome.CLARIFY
    assert clarified.state.status is AgentStatus.CLARIFYING


def test_forged_source_invalid_parameter_duplicate_and_budget_are_safe_failures() -> None:
    executor = ControlledAgentExecutor()
    validator = ToolPlanValidator(executor=executor)
    forged = PlanValidationContext(
        authorized_user_id="USER-1",
        trusted_parameters=(
            TrustedParameter(
                name="order_id", value="ORD-OTHER", source=ParameterSource.USER_CANDIDATE
            ),
        ),
    )
    assert (
        validator.validate(_state(executor), _plan(), forged).reason_code
        is AgentReasonCode.TOOL_PARAMETER_SOURCE_UNTRUSTED
    )
    invalid = _plan("policy.lookup")
    assert (
        validator.validate(_state(executor), invalid, _context()).reason_code
        is AgentReasonCode.TOOL_PARAMETER_INVALID
    )
    with pytest.raises(ValidationError):
        AgentPlanCandidate.model_validate(
            {
                **_plan().model_dump(),
                "extracted_parameters": {"order_id": "ORD-1", "user_id": "ADMIN"},
            }
        )
    denied = _context().model_copy(update={"authorized_user_id": "USER-OTHER"})
    assert (
        validator.validate(_state(executor), _plan(), denied).reason_code
        is AgentReasonCode.TOOL_PERMISSION_DENIED
    )
    call_key = "order.get_authorized:order_id=ORD-1"
    assert (
        validator.validate(_state(executor), _plan(), _context(calls=(call_key,))).reason_code
        is AgentReasonCode.TOOL_DUPLICATE_CALL
    )
    limited = ControlledAgentExecutor(AgentExecutionPolicy(max_budget_units=1))
    state = _state(limited).model_copy(update={"budget_used": 1})
    assert (
        ToolPlanValidator(executor=limited).validate(state, _plan(), _context()).reason_code
        is AgentReasonCode.TOOL_BUDGET_EXCEEDED
    )
