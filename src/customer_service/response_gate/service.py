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

    _UNSAFE_PATTERN = re.compile(r"(?:traceback|password=|fake://|internal server)", re.IGNORECASE)
    _SAFE_MESSAGE = "暂时无法安全确认处理结果，请补充信息或由人工协助处理。"

    def evaluate(
        self, draft: ResponseDraft, *, evidence: ResponseEvidenceContext
    ) -> ResponseGateResult:
        reasons: list[ResponseGateReason] = []
        if self._UNSAFE_PATTERN.search(draft.message):
            return self._safe_rewrite((ResponseGateReason.UNSAFE_CONTENT,))
        rendered = self.render_grounded(draft)
        if rendered is None or draft.message != rendered:
            reasons.append(ResponseGateReason.UNSUPPORTED_FREE_TEXT)
        if draft.claims_policy_conclusion and not self._citations_grounded(draft, evidence):
            reasons.append(ResponseGateReason.UNGROUNDED_POLICY)
        if draft.claims_order_facts and draft.order != evidence.order:
            reasons.append(ResponseGateReason.UNAUTHORIZED_ORDER_FACT)
        if draft.claims_eligibility and draft.eligibility != evidence.eligibility:
            reasons.append(ResponseGateReason.ELIGIBILITY_MISMATCH)
        if draft.approval is not None and draft.approval != evidence.approval:
            reasons.append(ResponseGateReason.INVALID_APPROVAL)

        reasons.extend(self._evidence_consistency_reasons(evidence))

        if draft.claims_completion and not self._completion_grounded(draft, evidence):
            reasons.append(ResponseGateReason.UNCONFIRMED_COMPLETION)
        if (
            evidence.eligibility is not None
            and evidence.eligibility.requires_human_approval
            and draft.claims_completion
        ):
            if not self._approved(evidence):
                reasons.append(ResponseGateReason.APPROVAL_REQUIRED)
            elif draft.approval != evidence.approval:
                reasons.append(ResponseGateReason.INVALID_APPROVAL)

        if not reasons:
            assert rendered is not None
            return ResponseGateResult(
                action=ResponseGateAction.ALLOW,
                reasons=(),
                message=rendered,
                response=draft,
            )
        unique = tuple(dict.fromkeys(reasons))
        high_risk = bool(
            evidence.eligibility is not None and evidence.eligibility.requires_human_approval
        )
        if unique == (ResponseGateReason.UNSUPPORTED_FREE_TEXT,) and not high_risk:
            return self._safe_rewrite(unique)
        action = (
            ResponseGateAction.ESCALATE
            if (high_risk and unique == (ResponseGateReason.UNSUPPORTED_FREE_TEXT,))
            or any(
                reason
                in {ResponseGateReason.APPROVAL_REQUIRED, ResponseGateReason.INVALID_APPROVAL}
                for reason in unique
            )
            else ResponseGateAction.CLARIFY
        )
        return ResponseGateResult(
            action=action,
            reasons=unique,
            message=self._SAFE_MESSAGE,
            response=None,
        )

    @classmethod
    def render_grounded(cls, draft: ResponseDraft) -> str | None:
        """Render facts only from typed declarations; model prose is never a fact source."""
        fragments: list[str] = []
        if draft.claims_policy_conclusion:
            fragments.append("已找到与本次问题相关的当前政策证据。")
        if draft.claims_order_facts and draft.order is not None:
            fragments.append(f"订单 {draft.order.order_id} 当前状态为 {draft.order.status}。")
        if draft.claims_eligibility and draft.eligibility is not None:
            eligibility_messages = {
                "eligible": "该商品符合当前退货资格要求。",
                "ineligible": "该商品不符合当前退货资格要求。",
                "requires_approval": "该退货申请需要人工审批。",
                "needs_information": "当前信息不足以确认退货资格。",
                "verification_required": "当前退货资格需要进一步核验。",
            }
            fragments.append(eligibility_messages[draft.eligibility.status.value])
        if draft.approval is not None:
            approval_messages = {
                "pending": "人工审批仍在等待处理。",
                "approved": "人工审批已批准。",
                "adjusted": "人工审批要求补充或调整信息。",
                "rejected": "人工审批已拒绝。",
            }
            fragments.append(approval_messages[draft.approval.status.value])
        if draft.claims_completion and draft.service_case is not None:
            fragments.append(f"售后申请已创建，编号为 {draft.service_case.service_case_id}。")
        return "".join(fragments) or None

    @classmethod
    def contains_unsafe_text(cls, message: str) -> bool:
        return bool(cls._UNSAFE_PATTERN.search(message))

    @classmethod
    def _safe_rewrite(cls, reasons: tuple[ResponseGateReason, ...]) -> ResponseGateResult:
        rewritten = ResponseDraft(message=cls._SAFE_MESSAGE)
        return ResponseGateResult(
            action=ResponseGateAction.SAFE_REWRITE,
            reasons=reasons,
            message=rewritten.message,
            response=rewritten,
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
