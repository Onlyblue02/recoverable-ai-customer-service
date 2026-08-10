from datetime import UTC, datetime
from pathlib import Path

import pytest

from customer_service.agent_runtime.executor import ControlledAgentExecutor
from customer_service.agent_runtime.schemas import AgentEventType, AgentState, AgentStatus
from customer_service.agent_tools.evidence import EvidenceRejectReason
from customer_service.agent_tools.execution import (
    ControlledToolExecutor,
    ExecutionPermitVerifier,
    _ExecutionPermitAuthority,
)
from customer_service.agent_tools.schemas import (
    EvidenceBinding,
    ParameterSource,
    PlanValidationContext,
    ToolId,
    TrustedParameter,
)
from customer_service.agent_tools.validator import ToolPlanValidator
from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.model_gateway.schemas import AgentPlanCandidate
from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.schemas import PolicyDocument, PolicyQuery
from customer_service.rag.service import PolicyAnswerService
from customer_service.service_cases.repository import InMemoryServiceCaseRepository
from customer_service.service_cases.service import ServiceCaseService
from customer_service.tools.order_tool import (
    OrderGatewayOutcome,
    OrderGatewayStatus,
    OrderQueryService,
)
from customer_service.tools.schemas import AuthorizedOrderFacts, AuthorizedOrderItem


class _Orders:
    def lookup(self, *, current_user_id: str, order_id: str) -> OrderGatewayOutcome:
        if current_user_id != "USER-1" or order_id != "ORD-1":
            return OrderGatewayOutcome(status=OrderGatewayStatus.UNAUTHORIZED)
        return OrderGatewayOutcome(
            status=OrderGatewayStatus.FOUND,
            order=AuthorizedOrderFacts(
                order_id="ORD-1",
                status="delivered",
                placed_at=datetime(2026, 8, 1, tzinfo=UTC),
                currency="CNY",
                total_amount="100.00",
                delivered_at=datetime(2026, 8, 8, tzinfo=UTC),
                items=(
                    AuthorizedOrderItem(
                        order_item_id="ITEM-1",
                        product_id="PROD-1",
                        quantity=1,
                        unit_price="100.00",
                        line_total="100.00",
                    ),
                ),
            ),
        )


class _PolicyContexts:
    def get(self, *, conversation_id: str, turn_id: str, user_id: str) -> PolicyQuery | None:
        if (conversation_id, turn_id, user_id) != ("CONV-1", "TURN-1", "USER-1"):
            return None
        return PolicyQuery(category="electronics", return_reason="changed_mind")


def _state(executor: ControlledAgentExecutor) -> AgentState:
    state = executor.receive_turn(conversation_id="CONV-1", turn_id="TURN-1", user_id="USER-1")
    return executor.accept_validated_model_plan(
        executor.apply_event(
            executor.apply_event(state, AgentEventType.USER_MESSAGE), AgentEventType.MODEL_RESULT
        )
    )


def _plan() -> AgentPlanCandidate:
    return AgentPlanCandidate.model_validate(
        {
            "schema_version": "agent-plan-v1",
            "intent": "order_query",
            "requested_capability": "order.get_authorized",
            "extracted_parameters": {"order_id": "ORD-1"},
            "clarification_fields": [],
            "uncertainty_reason": None,
        }
    )


def _tool(
    validator: ToolPlanValidator,
    *,
    cases: InMemoryServiceCaseRepository | None = None,
) -> ControlledToolExecutor:
    policy = PolicyDocument(
        policy_id="POL-1",
        policy_version="1",
        title="Policy",
        source="test",
        status="published",
        effective_from=datetime(2026, 1, 1).date(),
        effective_to=datetime(2026, 12, 31).date(),
        applicable_categories=("electronics",),
        return_reason="changed_mind",
        return_window_days=7,
        decision="allow_if_resalable",
        content="test",
    )
    catalog = PolicyCatalog(
        dataset_name="test",
        dataset_version="1",
        reference_date=datetime(2026, 8, 10).date(),
        policies=(policy,),
    )
    return ControlledToolExecutor(
        permits=validator.execution_verifier,
        orders=OrderQueryService(_Orders()),
        policies=PolicyAnswerService(catalog),
        catalog=catalog,
        product_categories={"PROD-1": "electronics"},
        eligibility=EligibilityEngine(
            EligibilityRuleConfig.from_json(Path("config/return-eligibility-rules.v1.json"))
        ),
        policy_contexts=_PolicyContexts(),
        service_cases=None if cases is None else ServiceCaseService(cases),
    )


def test_constructed_step_or_permit_cannot_bypass_validator() -> None:
    executor = ControlledAgentExecutor()
    validator = ToolPlanValidator(executor=executor)
    state = _state(executor)
    result = validator.validate(
        state,
        _plan(),
        PlanValidationContext(
            authorized_user_id="USER-1",
            trusted_parameters=(
                TrustedParameter(
                    name="order_id", value="ORD-1", source=ParameterSource.CONFIRMED_FIELD
                ),
            ),
        ),
    )
    assert result.permit is not None and result.step is not None
    assert not hasattr(validator.execution_verifier, "issue")
    assert not hasattr(validator.execution_verifier, "_issue_internal")
    assert not hasattr(_ExecutionPermitAuthority(), "issue")
    with pytest.raises(PermissionError):
        ExecutionPermitVerifier(_ExecutionPermitAuthority(), _token=object())
    attacker = _ExecutionPermitAuthority()
    arbitrary = result.step.model_copy(update={"call_key": "attacker-call"})
    attacker_permit = attacker._issue(state=state, step=arbitrary)
    assert (
        _tool(validator).execute(state=state, permit=attacker_permit).code
        == "EXECUTION_PERMIT_INVALID"
    )
    forged = result.permit.model_copy(update={"proof": "forged"})
    assert _tool(validator).execute(state=state, permit=forged).code == "EXECUTION_PERMIT_INVALID"
    # A genuine permit remains bound to exactly one validated state and executes once.
    executed = _tool(validator).execute(state=state, permit=result.permit)
    assert executed.code == "ORDER_FOUND"
    assert executed.evidence is not None
    assert executed.evidence.order_id == "ORD-1"
    assert executed.evidence.order_item_id is None
    assert all(field.name != "order_item_id" for field in executed.evidence.public_fields)
    assert (
        _tool(validator).execute(state=state, permit=result.permit).code
        == "EXECUTION_PERMIT_INVALID"
    )


def test_wrong_user_or_wrong_state_cannot_consume_a_validated_permit() -> None:
    executor = ControlledAgentExecutor()
    validator = ToolPlanValidator(executor=executor)
    state = _state(executor)
    result = validator.validate(
        state,
        _plan(),
        PlanValidationContext(
            authorized_user_id="USER-1",
            trusted_parameters=(
                TrustedParameter(
                    name="order_id", value="ORD-1", source=ParameterSource.CONFIRMED_FIELD
                ),
            ),
        ),
    )
    assert result.permit is not None
    wrong = state.model_copy(update={"user_id": "USER-OTHER"})
    assert (
        _tool(validator).execute(state=wrong, permit=result.permit).code
        == "EXECUTION_PERMIT_INVALID"
    )
    assert wrong.status is AgentStatus.VALIDATING_PLAN


def test_failed_order_lookup_never_issues_public_evidence() -> None:
    executor = ControlledAgentExecutor()
    validator = ToolPlanValidator(executor=executor)
    state = _state(executor)
    plan = _plan().model_copy(
        update={
            "extracted_parameters": _plan().extracted_parameters.model_copy(
                update={"order_id": "ORD-MISSING"}
            )
        }
    )
    result = validator.validate(
        state,
        plan,
        PlanValidationContext(
            authorized_user_id="USER-1",
            trusted_parameters=(
                TrustedParameter(
                    name="order_id",
                    value="ORD-MISSING",
                    source=ParameterSource.CONFIRMED_FIELD,
                ),
            ),
        ),
    )
    assert result.permit is not None
    executed = _tool(validator).execute(state=state, permit=result.permit)
    assert not executed.succeeded and executed.evidence is None


def test_policy_lookup_uses_server_context_and_issues_grounded_evidence() -> None:
    executor = ControlledAgentExecutor()
    validator = ToolPlanValidator(executor=executor)
    state = _state(executor)
    plan = _plan().model_copy(
        update={
            "intent": "policy_question",
            "requested_capability": "policy.lookup",
            "extracted_parameters": _plan().extracted_parameters.model_copy(
                update={"order_id": None}
            ),
        }
    )
    result = validator.validate(
        state,
        plan,
        PlanValidationContext(authorized_user_id="USER-1"),
    )
    assert result.permit is not None
    executed = _tool(validator).execute(state=state, permit=result.permit)
    assert executed.succeeded and executed.evidence is not None
    assert executed.policy_ids == ("POL-1",)
    assert executed.evidence.order_item_id is None
    assert all(field.name != "order_item_id" for field in executed.evidence.public_fields)


def test_return_evaluate_evidence_binds_trusted_order_item_and_policy_version() -> None:
    executor = ControlledAgentExecutor()
    validator = ToolPlanValidator(executor=executor)
    state = _state(executor)
    plan = _plan().model_copy(
        update={
            "intent": "return_request",
            "requested_capability": "return.evaluate",
            "extracted_parameters": _plan().extracted_parameters.model_copy(
                update={"return_reason": "changed_mind", "item_condition": "resalable"}
            ),
        }
    )
    trusted = (
        TrustedParameter(name="order_id", value="ORD-1", source=ParameterSource.CONFIRMED_FIELD),
        TrustedParameter(
            name="return_reason", value="changed_mind", source=ParameterSource.CONFIRMED_FIELD
        ),
        TrustedParameter(
            name="item_condition", value="resalable", source=ParameterSource.CONFIRMED_FIELD
        ),
    )
    validated = validator.validate(
        state,
        plan,
        PlanValidationContext(authorized_user_id="USER-1", trusted_parameters=trusted),
    )
    assert validated.permit is not None
    tool = _tool(validator)
    evaluated = tool.execute(state=state, permit=validated.permit)
    evidence = evaluated.evidence
    assert evidence is not None
    assert (evidence.order_id, evidence.order_item_id) == ("ORD-1", "ITEM-1")
    fields = {(field.name, field.value) for field in evidence.public_fields}
    assert {
        ("order_id", "ORD-1"),
        ("order_item_id", "ITEM-1"),
        ("eligibility_code", "eligible"),
        ("policy_id", "POL-1"),
        ("policy_version", "1"),
    } <= fields
    binding = EvidenceBinding(
        conversation_id="CONV-1",
        turn_id="TURN-1",
        user_id="USER-1",
        order_id="ORD-1",
        order_item_id="ITEM-1",
        expected_tool_id=ToolId.RETURN_EVALUATE,
        expected_contract_version="tool-contract-v1",
    )
    assert tool.evidence_verifier.verify(evidence, binding, now=datetime.now(UTC)) is None
    wrong_item = binding.model_copy(update={"order_item_id": "ITEM-OTHER"})
    assert (
        tool.evidence_verifier.verify(evidence, wrong_item, now=datetime.now(UTC))
        is EvidenceRejectReason.BINDING_MISMATCH
    )


def test_low_risk_write_requires_one_shot_continuation_and_is_idempotent() -> None:
    executor = ControlledAgentExecutor()
    validator = ToolPlanValidator(executor=executor)
    state = _state(executor)
    plan = _plan().model_copy(
        update={
            "intent": "return_request",
            "requested_capability": "return.evaluate",
            "extracted_parameters": _plan().extracted_parameters.model_copy(
                update={"return_reason": "changed_mind", "item_condition": "resalable"}
            ),
        }
    )
    trusted = (
        TrustedParameter(name="order_id", value="ORD-1", source=ParameterSource.CONFIRMED_FIELD),
        TrustedParameter(
            name="return_reason",
            value="changed_mind",
            source=ParameterSource.CONFIRMED_FIELD,
        ),
        TrustedParameter(
            name="item_condition",
            value="resalable",
            source=ParameterSource.CONFIRMED_FIELD,
        ),
    )
    validated = validator.validate(
        state,
        plan,
        PlanValidationContext(authorized_user_id="USER-1", trusted_parameters=trusted),
    )
    assert validated.permit is not None
    cases = InMemoryServiceCaseRepository()
    tool = _tool(validator, cases=cases)
    evaluated = tool.execute(state=state, permit=validated.permit)
    assert evaluated.evidence is not None
    assert evaluated.evidence.order_item_id == "ITEM-1"
    assert evaluated.continuation_state is not None and len(evaluated.continuations) == 1
    continuation = evaluated.continuations[0]
    forged_state = evaluated.continuation_state.model_copy(update={"user_id": "USER-OTHER"})
    assert tool.execute(state=forged_state, permit=continuation).code == "EXECUTION_PERMIT_INVALID"
    created = tool.execute(state=evaluated.continuation_state, permit=continuation)
    repeated = tool.execute(state=evaluated.continuation_state, permit=continuation)
    assert created.succeeded and created.evidence is not None and cases.case_count == 1
    assert created.evidence.order_item_id == evaluated.evidence.order_item_id
    assert repeated.code == "EXECUTION_PERMIT_INVALID"
