from datetime import datetime

import pytest

from customer_service.approvals.schemas import ApprovalDecision, ApprovalStatus, ApprovalTaskSummary
from customer_service.eligibility.schemas import (
    EligibilityConclusion,
    EligibilityInputBinding,
    EligibilityResult,
    EligibilityStatus,
    RiskReason,
)
from customer_service.rag.schemas import PolicyCitation
from customer_service.response_gate.schemas import (
    ResponseDraft,
    ResponseEvidenceContext,
    ResponseGateAction,
    ResponseGateReason,
)
from customer_service.response_gate.service import ResponseGateService
from customer_service.service_cases.schemas import ServiceCaseSummary
from customer_service.tools.schemas import AuthorizedOrderFacts, AuthorizedOrderItem


def order(order_id: str = "ORD-NORMAL-001") -> AuthorizedOrderFacts:
    return AuthorizedOrderFacts(
        order_id=order_id,
        status="delivered",
        placed_at=datetime(2026, 7, 1),
        delivered_at=datetime(2026, 7, 2),
        currency="CNY",
        total_amount="129.00",
        items=(
            AuthorizedOrderItem(
                order_item_id="ITEM-1",
                product_id="PROD-1",
                quantity=1,
                unit_price="129.00",
                line_total="129.00",
            ),
        ),
    )


def citation(source: str = "synthetic://policy") -> PolicyCitation:
    return PolicyCitation(
        policy_id="POL-1",
        evidence_id="policy:POL-1:1.0.0",
        policy_version="1.0.0",
        title="policy",
        source=source,
        effective_from=datetime(2026, 1, 1).date(),
        effective_to=datetime(2026, 12, 31).date(),
        excerpt="return within seven days",
    )


def eligibility(*, high_risk: bool = False) -> EligibilityResult:
    return EligibilityResult(
        rule_version="1.0.0",
        status=EligibilityStatus.REQUIRES_APPROVAL if high_risk else EligibilityStatus.ELIGIBLE,
        eligibility=EligibilityConclusion.INDETERMINATE
        if high_risk
        else EligibilityConclusion.ELIGIBLE,
        applicable_policy_ids=("POL-1",),
        matched_rule_ids=("HIGH_VALUE_THRESHOLD",) if high_risk else ("RETURN_WINDOW",),
        missing_fields=(),
        risk_reasons=(RiskReason.HIGH_VALUE_ORDER,) if high_risk else (),
        requires_human_approval=high_risk,
        days_since_delivery=2,
        message="result",
        input_binding=EligibilityInputBinding(
            order_id="ORD-NORMAL-001",
            order_item_id="ITEM-1",
            product_id="PROD-1",
            rule_version="1.0.0",
        ),
    )


def evidence(*, high_risk: bool = False, approved: bool = False) -> ResponseEvidenceContext:
    current = eligibility(high_risk=high_risk)
    approval = None
    if approved:
        approval = ApprovalTaskSummary(
            approval_id="APR-1",
            status=ApprovalStatus.APPROVED,
            version=2,
            conversation_summary="review",
            user_id="USR-DEMO-001",
            order=order(),
            order_item_id="ITEM-1",
            policy_citations=(citation(),),
            eligibility=current,
            risk_reasons=("HIGH_VALUE_ORDER",),
            decision=ApprovalDecision.APPROVE,
            note="approved",
            recommendation=None,
            decided_by="AGENT-1",
            decided_at=datetime(2026, 7, 3),
        )
    return ResponseEvidenceContext(
        policy_citations=(citation(),),
        current_user_id="USR-DEMO-001",
        order=order(),
        eligibility=current,
        service_case=ServiceCaseSummary(
            service_case_id="SC-1",
            status="created",
            order_id="ORD-NORMAL-001",
            order_item_id="ITEM-1",
        ),
        approval=approval,
    )


def grounded_draft(*, high_risk: bool = False, approved: bool = False) -> ResponseDraft:
    trusted = evidence(high_risk=high_risk, approved=approved)
    draft = ResponseDraft(
        message="申请已创建。",
        policy_citations=trusted.policy_citations,
        order=trusted.order,
        eligibility=trusted.eligibility,
        service_case=trusted.service_case,
        approval=trusted.approval,
        claims_policy_conclusion=True,
        claims_order_facts=True,
        claims_eligibility=True,
        claims_completion=True,
    )
    rendered = ResponseGateService.render_grounded(draft)
    assert rendered is not None
    return draft.model_copy(update={"message": rendered})


def test_grounded_standard_completion_is_allowed() -> None:
    result = ResponseGateService().evaluate(grounded_draft(), evidence=evidence())
    assert result.action is ResponseGateAction.ALLOW and result.response is not None


@pytest.mark.parametrize(
    "changed",
    [
        {"title": "tampered title"},
        {"effective_from": datetime(2026, 2, 1).date()},
        {"effective_to": datetime(2025, 12, 31).date()},
        {"excerpt": "tampered excerpt"},
    ],
)
def test_policy_citation_requires_complete_trusted_equality(changed: dict[str, object]) -> None:
    forged = citation().model_copy(update=changed)
    result = ResponseGateService().evaluate(
        ResponseDraft(
            message="政策允许退货", policy_citations=(forged,), claims_policy_conclusion=True
        ),
        evidence=evidence(),
    )
    assert result.action is ResponseGateAction.CLARIFY
    assert ResponseGateReason.UNGROUNDED_POLICY in result.reasons and result.response is None


@pytest.mark.parametrize(
    "draft, expected",
    [
        (
            ResponseDraft(
                message="政策允许退货",
                policy_citations=(citation("fake://source"),),
                claims_policy_conclusion=True,
            ),
            ResponseGateReason.UNGROUNDED_POLICY,
        ),
        (
            ResponseDraft(
                message="订单已送达", order=order("ORD-OTHER-001"), claims_order_facts=True
            ),
            ResponseGateReason.UNAUTHORIZED_ORDER_FACT,
        ),
        (ResponseDraft(message="申请已创建"), ResponseGateReason.UNSUPPORTED_FREE_TEXT),
    ],
)
def test_unsupported_public_claims_are_blocked(
    draft: ResponseDraft, expected: ResponseGateReason
) -> None:
    result = ResponseGateService().evaluate(draft, evidence=evidence())
    assert result.action in {ResponseGateAction.CLARIFY, ResponseGateAction.SAFE_REWRITE}
    assert expected in result.reasons


def test_sensitive_text_is_safely_rewritten_without_facts() -> None:
    result = ResponseGateService().evaluate(
        ResponseDraft(message="traceback password=secret"), evidence=evidence()
    )
    assert result.action is ResponseGateAction.SAFE_REWRITE
    assert result.response is not None and "password" not in result.message


@pytest.mark.parametrize(
    "message",
    (
        "您可以退款。",
        "可以退货。",
        "不能退款。",
        "可办理退货。",
        "会为您退款。",
    ),
)
def test_unstructured_return_conclusions_are_never_allowed(message: str) -> None:
    gate = ResponseGateService()
    empty = gate.evaluate(ResponseDraft(message=message), evidence=ResponseEvidenceContext())
    order_only = gate.evaluate(
        ResponseDraft(message=message),
        evidence=ResponseEvidenceContext(current_user_id="USR-DEMO-001", order=order()),
    )
    policy_only = gate.evaluate(
        ResponseDraft(message=message),
        evidence=ResponseEvidenceContext(policy_citations=(citation(),)),
    )

    for result in (empty, order_only, policy_only):
        assert result.action is not ResponseGateAction.ALLOW
        assert message not in result.message


@pytest.mark.parametrize("message", ("已批准。", "已完成。", "会为您处理。"))
def test_unstructured_high_risk_success_synonyms_are_never_allowed(message: str) -> None:
    result = ResponseGateService().evaluate(
        ResponseDraft(message=message), evidence=evidence(high_risk=True)
    )
    assert result.action is not ResponseGateAction.ALLOW
    assert message not in result.message


def test_high_risk_completion_without_approval_escalates() -> None:
    result = ResponseGateService().evaluate(grounded_draft(), evidence=evidence(high_risk=True))
    assert result.action is ResponseGateAction.ESCALATE
    assert ResponseGateReason.APPROVAL_REQUIRED in result.reasons and result.response is None


def test_high_risk_approved_completion_is_allowed() -> None:
    result = ResponseGateService().evaluate(
        grounded_draft(high_risk=True, approved=True),
        evidence=evidence(high_risk=True, approved=True),
    )
    assert result.action is ResponseGateAction.ALLOW


@pytest.mark.parametrize(
    "tamper",
    ["approval_user", "approval_order", "eligibility_binding", "service_case", "approval_policy"],
)
def test_cross_domain_high_risk_evidence_drift_never_allows_completion(tamper: str) -> None:
    trusted = evidence(high_risk=True, approved=True)
    approval = trusted.approval
    current_eligibility = trusted.eligibility
    assert approval is not None and current_eligibility is not None
    if tamper == "approval_user":
        trusted = trusted.model_copy(
            update={"approval": approval.model_copy(update={"user_id": "USR-OTHER-001"})}
        )
    elif tamper == "approval_order":
        trusted = trusted.model_copy(
            update={"approval": approval.model_copy(update={"order": order("ORD-OTHER-001")})}
        )
    elif tamper == "eligibility_binding":
        binding = current_eligibility.input_binding
        assert binding is not None
        trusted = trusted.model_copy(
            update={
                "eligibility": current_eligibility.model_copy(
                    update={
                        "input_binding": binding.model_copy(update={"order_item_id": "ITEM-OTHER"})
                    }
                )
            }
        )
    elif tamper == "service_case":
        assert trusted.service_case is not None
        trusted = trusted.model_copy(
            update={
                "service_case": trusted.service_case.model_copy(
                    update={"order_id": "ORD-OTHER-001"}
                )
            }
        )
    else:
        trusted = trusted.model_copy(
            update={
                "approval": approval.model_copy(
                    update={"policy_citations": (citation("synthetic://other"),)}
                )
            }
        )
    result = ResponseGateService().evaluate(
        grounded_draft(high_risk=True, approved=True), evidence=trusted
    )
    assert result.action in {ResponseGateAction.CLARIFY, ResponseGateAction.ESCALATE}
    assert result.response is None
