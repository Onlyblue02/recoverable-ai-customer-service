import json
from pathlib import Path
from typing import Any, cast

from customer_service.approvals.repository import InMemoryApprovalTaskRepository
from customer_service.approvals.schemas import (
    ApprovalActorContext,
    ApprovalDecision,
    ApprovalDecisionRequest,
    ApprovalStatus,
    ApprovalTaskContext,
    ApprovalTaskCreateRequest,
    ApprovalTaskResult,
    ApprovalTaskResultStatus,
)
from customer_service.approvals.service import ApprovalTaskService
from customer_service.eligibility.schemas import (
    EligibilityConclusion,
    EligibilityInputBinding,
    EligibilityResult,
    EligibilityStatus,
    RiskReason,
)
from customer_service.rag.schemas import PolicyCitation
from customer_service.tools.schemas import AuthorizedOrderFacts

ROOT = Path(__file__).parents[3]
CASES_PATH = ROOT / "data" / "evaluation" / "graph" / "cases.v1.json"


def _case(case_id: str) -> dict[str, Any]:
    document = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return cast(
        dict[str, Any], next(case for case in document["cases"] if case["case_id"] == case_id)
    )


def _context(order_id: str, *, risk: RiskReason) -> ApprovalTaskContext:
    order = AuthorizedOrderFacts.model_validate(
        {
            "order_id": order_id,
            "status": "delivered",
            "placed_at": "2026-07-15T09:00:00+00:00",
            "delivered_at": "2026-07-18T10:00:00+00:00",
            "currency": "CNY",
            "total_amount": "9999.00" if risk is RiskReason.HIGH_VALUE_ORDER else "129.00",
            "items": [
                {
                    "order_item_id": "ITEM-T002-001",
                    "product_id": "PROD-GENERAL-001",
                    "quantity": 1,
                    "unit_price": "129.00",
                    "line_total": "129.00",
                }
            ],
        }
    )
    eligibility = EligibilityResult(
        rule_version="1.0.0",
        status=EligibilityStatus.REQUIRES_APPROVAL,
        eligibility=EligibilityConclusion.INDETERMINATE,
        applicable_policy_ids=("POL-ACTIVE-STANDARD-001",),
        matched_rule_ids=("HIGH_VALUE_THRESHOLD",),
        missing_fields=(),
        risk_reasons=(risk,),
        requires_human_approval=True,
        days_since_delivery=2,
        message="需要人工审批。",
        input_binding=EligibilityInputBinding(
            order_id=order_id,
            order_item_id="ITEM-T002-001",
            product_id="PROD-GENERAL-001",
            rule_version="1.0.0",
        ),
    )
    citation = PolicyCitation.model_validate(
        {
            "policy_id": "POL-ACTIVE-STANDARD-001",
            "evidence_id": "policy:POL-ACTIVE-STANDARD-001:1.0.0",
            "policy_version": "1.0.0",
            "title": "标准退货政策",
            "source": "synthetic://policies/standard-v1",
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "excerpt": "高风险订单需要人工审批。",
        }
    )
    return ApprovalTaskContext(
        current_user_id="USR-DEMO-001",
        order=order,
        order_item_id="ITEM-T002-001",
        eligibility=eligibility,
        policy_citations=(citation,),
    )


def _create(service: ApprovalTaskService, context: ApprovalTaskContext) -> ApprovalTaskResult:
    return service.create(
        ApprovalTaskCreateRequest(conversation_summary="高风险退货已完成事实收集。"),
        context=context,
    )


def test_t002_approval_cases_use_public_service_path() -> None:
    approve_case = _case("AC-FR08-N-001")
    adjust_case = _case("AC-FR08-E-001")
    reject_case = _case("AC-FR08-E-002")
    duplicate_case = _case("AC-FR08-E-003")
    service = ApprovalTaskService(InMemoryApprovalTaskRepository())

    approved = _create(service, _context("ORD-HIGH-VALUE-001", risk=RiskReason.HIGH_VALUE_ORDER))
    assert approved.status is ApprovalTaskResultStatus.CREATED
    assert approved.approval is not None
    approved_result = service.decide(
        approved.approval.approval_id,
        ApprovalDecisionRequest(
            decision=ApprovalDecision.APPROVE, note="已确认。", expected_version=1
        ),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    assert approved_result.status is ApprovalTaskResultStatus.DECIDED
    assert approved_result.approval is not None
    assert approved_result.approval.status is ApprovalStatus.APPROVED
    assert approve_case["expected_terminal_state"]["business_effects"]["service_cases_created"] == 1

    adjusted = _create(service, _context("ORD-HIGH-VALUE-002", risk=RiskReason.HIGH_VALUE_ORDER))
    assert adjusted.approval is not None
    adjusted_result = service.decide(
        adjusted.approval.approval_id,
        ApprovalDecisionRequest(
            decision=ApprovalDecision.ADJUST,
            note="先补充材料。",
            recommendation="先补充商品照片再处理",
            expected_version=1,
        ),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    assert adjusted_result.approval is not None
    assert adjusted_result.approval.status is ApprovalStatus.ADJUSTED
    assert adjust_case["expected_terminal_state"]["business_effects"]["service_cases_created"] == 0

    rejected = _create(service, _context("ORD-OVERDUE-001", risk=RiskReason.OVERDUE_EXCEPTION))
    assert rejected.approval is not None
    rejected_result = service.decide(
        rejected.approval.approval_id,
        ApprovalDecisionRequest(
            decision=ApprovalDecision.REJECT, note="超期不予特批。", expected_version=1
        ),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    assert rejected_result.approval is not None
    assert rejected_result.approval.status is ApprovalStatus.REJECTED
    assert reject_case["expected_terminal_state"]["business_effects"]["service_cases_created"] == 0

    duplicate = service.decide(
        approved.approval.approval_id,
        ApprovalDecisionRequest(
            decision=ApprovalDecision.REJECT, note="重复决定。", expected_version=2
        ),
        actor_context=ApprovalActorContext(actor_id="USR-AGENT-001"),
    )
    assert duplicate.status is ApprovalTaskResultStatus.BLOCKED
    assert (
        duplicate_case["expected_terminal_state"]["business_effects"]["service_cases_created"] == 0
    )
