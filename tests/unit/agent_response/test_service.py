from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from customer_service.agent_response.schemas import AgentResponseOutcome
from customer_service.agent_response.service import AgentResponseService
from customer_service.agent_runtime.executor import ControlledAgentExecutor
from customer_service.agent_runtime.schemas import AgentEventType, AgentState, AgentStatus
from customer_service.agent_tools.execution import ControlledToolExecutor
from customer_service.agent_tools.schemas import (
    EvidenceRecord,
    ParameterSource,
    PlanValidationContext,
    TrustedParameter,
)
from customer_service.agent_tools.validator import ToolPlanValidator
from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.model_gateway.fake import FakeModelGateway
from customer_service.model_gateway.schemas import AgentPlanCandidate
from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.schemas import PolicyDocument, PolicyQuery
from customer_service.rag.service import PolicyAnswerService
from customer_service.response_gate.schemas import ResponseGateAction
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
        if (current_user_id, order_id) != ("USER-1", "ORD-1"):
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
        if (conversation_id, turn_id, user_id) == ("CONV-1", "TURN-1", "USER-1"):
            return PolicyQuery(category="electronics", return_reason="changed_mind")
        return None


def _runtime_state(executor: ControlledAgentExecutor) -> AgentState:
    state = executor.receive_turn(conversation_id="CONV-1", turn_id="TURN-1", user_id="USER-1")
    state = executor.apply_event(state, AgentEventType.USER_MESSAGE)
    state = executor.apply_event(state, AgentEventType.MODEL_RESULT)
    return executor.accept_validated_model_plan(state)


def _catalog() -> PolicyCatalog:
    return PolicyCatalog(
        dataset_name="test",
        dataset_version="1",
        reference_date=datetime(2026, 8, 10).date(),
        policies=(
            PolicyDocument(
                policy_id="POL-1",
                policy_version="1",
                title="七日退货政策",
                source="kb://policy/POL-1",
                status="published",
                effective_from=datetime(2026, 1, 1).date(),
                effective_to=datetime(2026, 12, 31).date(),
                applicable_categories=("electronics",),
                return_reason="changed_mind",
                return_window_days=7,
                decision="allow_if_resalable",
                content="签收后七日内且商品可再次销售时允许申请退货。",
            ),
        ),
    )


def _plan(capability: str) -> AgentPlanCandidate:
    payload: dict[str, object] = {
        "schema_version": "agent-plan-v1",
        "intent": "order_query" if capability == "order.get_authorized" else "policy_question",
        "requested_capability": capability,
        "extracted_parameters": {"order_id": "ORD-1" if capability.startswith("order") else None},
        "clarification_fields": [],
        "uncertainty_reason": None,
    }
    return AgentPlanCandidate.model_validate(payload)


def _executed(
    capability: str,
) -> tuple[ControlledAgentExecutor, ControlledToolExecutor, AgentState, EvidenceRecord]:
    executor = ControlledAgentExecutor()
    state = _runtime_state(executor)
    validator = ToolPlanValidator(executor=executor)
    trusted = (
        (TrustedParameter(name="order_id", value="ORD-1", source=ParameterSource.CONFIRMED_FIELD),)
        if capability == "order.get_authorized"
        else ()
    )
    validated = validator.validate(
        state,
        _plan(capability),
        PlanValidationContext(authorized_user_id="USER-1", trusted_parameters=trusted),
    )
    assert validated.permit is not None
    catalog = _catalog()
    tools = ControlledToolExecutor(
        permits=validator.execution_verifier,
        orders=OrderQueryService(_Orders()),
        policies=PolicyAnswerService(catalog),
        catalog=catalog,
        product_categories={"PROD-1": "electronics"},
        eligibility=EligibilityEngine(
            EligibilityRuleConfig.from_json(Path("config/return-eligibility-rules.v1.json"))
        ),
        policy_contexts=_PolicyContexts(),
    )
    result = tools.execute(state=state, permit=validated.permit)
    assert result.evidence is not None
    drafting = state.model_copy(update={"status": AgentStatus.DRAFTING})
    return executor, tools, drafting, result.evidence


def _payload(
    evidence_id: str,
    *,
    text: str = "订单 ORD-1 当前状态为 delivered。",
    claim: str = "order",
) -> dict[str, object]:
    return {
        "schema_version": "agent-response-draft-v1",
        "text": text,
        "claims": [{"claim_type": claim, "evidence_ids": [evidence_id]}],
    }


def _completed_case() -> tuple[
    ControlledAgentExecutor,
    ControlledToolExecutor,
    AgentState,
    tuple[EvidenceRecord, EvidenceRecord],
]:
    executor = ControlledAgentExecutor()
    state = _runtime_state(executor)
    validator = ToolPlanValidator(executor=executor)
    plan = AgentPlanCandidate.model_validate(
        {
            "schema_version": "agent-plan-v1",
            "intent": "return_request",
            "requested_capability": "return.evaluate",
            "extracted_parameters": {
                "order_id": "ORD-1",
                "return_reason": "changed_mind",
                "item_condition": "resalable",
            },
            "clarification_fields": [],
            "uncertainty_reason": None,
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
    catalog = _catalog()
    tool = ControlledToolExecutor(
        permits=validator.execution_verifier,
        orders=OrderQueryService(_Orders()),
        policies=PolicyAnswerService(catalog),
        catalog=catalog,
        product_categories={"PROD-1": "electronics"},
        eligibility=EligibilityEngine(
            EligibilityRuleConfig.from_json(Path("config/return-eligibility-rules.v1.json"))
        ),
        service_cases=ServiceCaseService(InMemoryServiceCaseRepository()),
    )
    evaluated = tool.execute(state=state, permit=validated.permit)
    assert evaluated.evidence is not None and evaluated.continuation_state is not None
    created = tool.execute(state=evaluated.continuation_state, permit=evaluated.continuations[0])
    assert created.evidence is not None
    return (
        executor,
        tool,
        state.model_copy(update={"status": AgentStatus.DRAFTING}),
        (evaluated.evidence, created.evidence),
    )


def test_valid_current_turn_order_evidence_is_allowed_by_gate() -> None:
    executor, tools, state, evidence = _executed("order.get_authorized")
    service = AgentResponseService(
        executor=executor,
        model_gateway=FakeModelGateway({"TURN-1": _payload(evidence.evidence_id)}),
        evidence_verifier=tools.evidence_verifier,
    )
    result = service.generate(
        state,
        text="查询订单",
        evidence=(evidence,),
        prompt_version="t606-v1",
    )

    assert result.outcome is AgentResponseOutcome.ALLOWED
    assert result.state.status is AgentStatus.COMPLETED
    assert result.public_response == "订单 ORD-1 当前状态为 delivered。"
    assert result.gate is not None and result.gate.action is ResponseGateAction.ALLOW
    assert "查询订单" not in result.audit.model_dump_json()


def test_real_policy_evidence_is_the_only_source_of_policy_citation() -> None:
    executor, tools, state, evidence = _executed("policy.lookup")
    service = AgentResponseService(
        executor=executor,
        model_gateway=FakeModelGateway(
            {
                "TURN-1": _payload(
                    evidence.evidence_id,
                    text="已找到与本次问题相关的当前政策证据。",
                    claim="policy",
                )
            }
        ),
        evidence_verifier=tools.evidence_verifier,
    )
    result = service.generate(
        state, text="退货政策", evidence=(evidence,), prompt_version="t606-v1"
    )

    assert result.outcome is AgentResponseOutcome.ALLOWED
    assert result.gate is not None and result.gate.response is not None
    assert result.gate.response.policy_citations[0].policy_id == "POL-1"


def test_eligibility_and_created_case_require_their_actual_tool_evidence() -> None:
    executor, tools, state, evidence = _completed_case()
    case_id = next(
        field.value for field in evidence[1].public_fields if field.name == "service_case_id"
    )
    payload = {
        "schema_version": "agent-response-draft-v1",
        "text": (f"该商品符合当前退货资格要求。售后申请已创建，编号为 {case_id}。"),
        "claims": [
            {"claim_type": "eligibility", "evidence_ids": [evidence[0].evidence_id]},
            {"claim_type": "completion", "evidence_ids": [evidence[1].evidence_id]},
        ],
    }
    result = AgentResponseService(
        executor=executor,
        model_gateway=FakeModelGateway({"TURN-1": payload}),
        evidence_verifier=tools.evidence_verifier,
    ).generate(state, text="申请退货", evidence=evidence, prompt_version="t606-v1")

    assert result.outcome is AgentResponseOutcome.ALLOWED
    assert result.gate is not None and result.gate.action is ResponseGateAction.ALLOW


def test_unknown_reference_and_forged_record_fail_before_gate() -> None:
    executor, tools, state, evidence = _executed("order.get_authorized")
    unknown = AgentResponseService(
        executor=executor,
        model_gateway=FakeModelGateway({"TURN-1": _payload("EVD-UNKNOWN")}),
        evidence_verifier=tools.evidence_verifier,
    ).generate(state, text="x", evidence=(evidence,), prompt_version="t606-v1")
    assert unknown.outcome is AgentResponseOutcome.FAILED_SAFE and unknown.gate is None

    forged = evidence.model_copy(update={"proof": "forged"})
    rejected = AgentResponseService(
        executor=executor,
        model_gateway=FakeModelGateway({"TURN-1": _payload(forged.evidence_id)}),
        evidence_verifier=tools.evidence_verifier,
    ).generate(state, text="x", evidence=(forged,), prompt_version="t606-v1")
    assert rejected.outcome is AgentResponseOutcome.FAILED_SAFE and rejected.gate is None


def test_cross_turn_evidence_and_fabricated_business_object_are_rejected() -> None:
    executor, tools, state, evidence = _executed("order.get_authorized")
    cross_turn = state.model_copy(update={"turn_id": "TURN-OTHER"})
    service = AgentResponseService(
        executor=executor,
        model_gateway=FakeModelGateway({"TURN-OTHER": _payload(evidence.evidence_id)}),
        evidence_verifier=tools.evidence_verifier,
    )
    assert (
        service.generate(
            cross_turn, text="x", evidence=(evidence,), prompt_version="t606-v1"
        ).outcome
        is AgentResponseOutcome.FAILED_SAFE
    )

    fabricated = _payload(evidence.evidence_id)
    fabricated["order"] = {"order_id": "ORD-FAKE"}
    invalid = AgentResponseService(
        executor=executor,
        model_gateway=FakeModelGateway({"TURN-1": fabricated}),
        evidence_verifier=tools.evidence_verifier,
    ).generate(state, text="x", evidence=(evidence,), prompt_version="t606-v1")
    assert invalid.outcome is AgentResponseOutcome.FAILED_SAFE


def test_expired_invalidated_and_wrong_resource_evidence_are_rejected() -> None:
    executor, tools, state, evidence = _executed("order.get_authorized")
    service = AgentResponseService(
        executor=executor,
        model_gateway=FakeModelGateway({"TURN-1": _payload(evidence.evidence_id)}),
        evidence_verifier=tools.evidence_verifier,
    )
    expired = service.generate(
        state,
        text="x",
        evidence=(evidence,),
        prompt_version="t606-v1",
        now=evidence.expires_at + timedelta(seconds=1),
    )
    assert expired.outcome is AgentResponseOutcome.FAILED_SAFE

    tools.evidence_verifier.invalidate(evidence, reason="superseded")
    invalidated = service.generate(state, text="x", evidence=(evidence,), prompt_version="t606-v1")
    assert invalidated.outcome is AgentResponseOutcome.FAILED_SAFE

    wrong_order = evidence.model_copy(update={"order_id": "ORD-OTHER"})
    assert (
        service.generate(state, text="x", evidence=(wrong_order,), prompt_version="t606-v1").outcome
        is AgentResponseOutcome.FAILED_SAFE
    )


def test_gate_rejection_exposes_no_success_response() -> None:
    executor, tools, state, evidence = _executed("order.get_authorized")
    service = AgentResponseService(
        executor=executor,
        model_gateway=FakeModelGateway(
            {"TURN-1": _payload(evidence.evidence_id, text="申请已创建。")}
        ),
        evidence_verifier=tools.evidence_verifier,
    )
    result = service.generate(state, text="x", evidence=(evidence,), prompt_version="t606-v1")

    assert result.outcome is AgentResponseOutcome.SAFE_REWRITE
    assert result.public_response != "申请已创建。"
    assert result.gate is not None and result.gate.action is ResponseGateAction.SAFE_REWRITE


def test_unsafe_model_text_is_rewritten_without_exposing_the_draft() -> None:
    executor, tools, state, evidence = _executed("order.get_authorized")
    result = AgentResponseService(
        executor=executor,
        model_gateway=FakeModelGateway(
            {"TURN-1": _payload(evidence.evidence_id, text="traceback password=secret")}
        ),
        evidence_verifier=tools.evidence_verifier,
    ).generate(state, text="x", evidence=(evidence,), prompt_version="t606-v1")

    assert result.outcome is AgentResponseOutcome.SAFE_REWRITE
    assert result.public_response is not None and "password" not in result.public_response


def test_model_cannot_embed_order_eligibility_approval_or_reasoning_objects() -> None:
    executor, tools, state, evidence = _executed("order.get_authorized")
    for forbidden in ("order", "eligibility", "approval", "reasoning"):
        payload = _payload(evidence.evidence_id)
        payload[forbidden] = {"status": "approved", "order_id": "ORD-FAKE"}
        result = AgentResponseService(
            executor=executor,
            model_gateway=FakeModelGateway({"TURN-1": payload}),
            evidence_verifier=tools.evidence_verifier,
        ).generate(state, text="x", evidence=(evidence,), prompt_version="t606-v1")
        assert result.outcome is AgentResponseOutcome.FAILED_SAFE


@pytest.mark.parametrize(
    "fabricated_text",
    (
        "政策允许直接退款。",
        "订单已发货。",
        "该商品符合退货资格。",
        "审批已批准。",
    ),
)
def test_undeclared_factual_text_cannot_bypass_structured_claims(
    fabricated_text: str,
) -> None:
    executor, tools, state, evidence = _executed("order.get_authorized")
    payload = {
        "schema_version": "agent-response-draft-v1",
        "text": fabricated_text,
        "claims": [],
    }
    result = AgentResponseService(
        executor=executor,
        model_gateway=FakeModelGateway({"TURN-1": payload}),
        evidence_verifier=tools.evidence_verifier,
    ).generate(state, text="x", evidence=(evidence,), prompt_version="t606-v1")

    assert result.outcome in {
        AgentResponseOutcome.SAFE_REWRITE,
        AgentResponseOutcome.CLARIFY,
        AgentResponseOutcome.ESCALATE,
    }
    assert result.public_response != fabricated_text
