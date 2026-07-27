import re

from customer_service.approvals.schemas import ApprovalDecision, ApprovalStatus
from customer_service.response_gate.schemas import (
    ResponseDraft,
    ResponseEvidenceContext,
    ResponseGateAction,
    ResponseGateReason,
    ResponseGateResult,
)


class ResponseGateService:
    """Deterministically prevents unsupported cross-domain final claims."""

    _COMPLETION_PATTERN = re.compile(r"(?:已创建|已完成|处理完成|申请成功)")
    _UNSAFE_PATTERN = re.compile(r"(?:traceback|password=|fake://|internal server)", re.IGNORECASE)

    def evaluate(
        self, draft: ResponseDraft, *, evidence: ResponseEvidenceContext
    ) -> ResponseGateResult:
        reasons: list[ResponseGateReason] = []
        if self._UNSAFE_PATTERN.search(draft.message):
            reasons.append(ResponseGateReason.UNSAFE_CONTENT)
        if draft.claims_policy_conclusion and not self._citations_grounded(draft, evidence):
            reasons.append(ResponseGateReason.UNGROUNDED_POLICY)
        if draft.claims_order_facts and draft.order != evidence.order:
            reasons.append(ResponseGateReason.UNAUTHORIZED_ORDER_FACT)
        if draft.claims_eligibility and draft.eligibility != evidence.eligibility:
            reasons.append(ResponseGateReason.ELIGIBILITY_MISMATCH)

        reasons.extend(self._evidence_consistency_reasons(evidence))

        completion_words = bool(self._COMPLETION_PATTERN.search(draft.message))
        if (draft.claims_completion or completion_words) and not self._completion_grounded(
            draft, evidence
        ):
            reasons.append(ResponseGateReason.UNCONFIRMED_COMPLETION)
        if (
            evidence.eligibility is not None
            and evidence.eligibility.requires_human_approval
            and (draft.claims_completion or completion_words)
        ):
            if not self._approved(evidence):
                reasons.append(ResponseGateReason.APPROVAL_REQUIRED)
            elif draft.approval != evidence.approval:
                reasons.append(ResponseGateReason.INVALID_APPROVAL)

        if not reasons:
            return ResponseGateResult(
                action=ResponseGateAction.ALLOW,
                reasons=(),
                message=draft.message,
                response=draft,
            )
        unique = tuple(dict.fromkeys(reasons))
        if unique == (ResponseGateReason.UNSAFE_CONTENT,):
            rewritten = ResponseDraft(
                message="暂时无法安全确认处理结果，请补充信息或由人工协助处理。"
            )
            return ResponseGateResult(
                action=ResponseGateAction.SAFE_REWRITE,
                reasons=unique,
                message=rewritten.message,
                response=rewritten,
            )
        action = (
            ResponseGateAction.ESCALATE
            if any(
                reason
                in {ResponseGateReason.APPROVAL_REQUIRED, ResponseGateReason.INVALID_APPROVAL}
                for reason in unique
            )
            else ResponseGateAction.CLARIFY
        )
        return ResponseGateResult(
            action=action,
            reasons=unique,
            message="暂时无法安全确认处理结果，请补充信息或由人工协助处理。",
            response=None,
        )

    @staticmethod
    def _citations_grounded(draft: ResponseDraft, evidence: ResponseEvidenceContext) -> bool:
        return bool(draft.policy_citations) and all(
            citation in evidence.policy_citations for citation in draft.policy_citations
        )

    @staticmethod
    def _completion_grounded(draft: ResponseDraft, evidence: ResponseEvidenceContext) -> bool:
        return (
            draft.service_case is not None
            and draft.service_case == evidence.service_case
            and draft.service_case.status == "created"
        )

    @staticmethod
    def _approved(evidence: ResponseEvidenceContext) -> bool:
        return (
            evidence.approval is not None
            and evidence.approval.status is ApprovalStatus.APPROVED
            and evidence.approval.decision is ApprovalDecision.APPROVE
        )

    def _evidence_consistency_reasons(
        self, evidence: ResponseEvidenceContext
    ) -> list[ResponseGateReason]:
        reasons: list[ResponseGateReason] = []
        eligibility = evidence.eligibility
        order = evidence.order
        if eligibility is not None:
            binding = eligibility.input_binding
            target = (
                next(
                    (item for item in order.items if item.order_item_id == binding.order_item_id),
                    None,
                )
                if order is not None and binding is not None
                else None
            )
            if (
                binding is None
                or order is None
                or binding.order_id != order.order_id
                or target is None
                or binding.product_id != target.product_id
            ):
                reasons.append(ResponseGateReason.ELIGIBILITY_MISMATCH)
            if evidence.service_case is not None and (
                binding is None
                or evidence.service_case.order_id != binding.order_id
                or evidence.service_case.order_item_id != binding.order_item_id
            ):
                reasons.append(ResponseGateReason.UNCONFIRMED_COMPLETION)
        elif evidence.service_case is not None:
            reasons.append(ResponseGateReason.UNCONFIRMED_COMPLETION)

        if (
            eligibility is not None
            and eligibility.requires_human_approval
            and evidence.approval is not None
            and not self._approval_binds(evidence)
        ):
            reasons.append(ResponseGateReason.INVALID_APPROVAL)
        return reasons

    @staticmethod
    def _approval_binds(evidence: ResponseEvidenceContext) -> bool:
        approval = evidence.approval
        eligibility = evidence.eligibility
        binding = eligibility.input_binding if eligibility is not None else None
        if (
            approval is None
            or binding is None
            or evidence.current_user_id is None
            or approval.user_id != evidence.current_user_id
            or approval.order != evidence.order
            or approval.order_item_id != binding.order_item_id
        ):
            return False
        return (
            approval.policy_citations == evidence.policy_citations
            and approval.eligibility == eligibility
        )
