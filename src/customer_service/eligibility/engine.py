from datetime import date

from customer_service.eligibility.config import EligibilityRuleConfig
from customer_service.eligibility.schemas import (
    EligibilityConclusion,
    EligibilityInputBinding,
    EligibilityRequest,
    EligibilityResult,
    EligibilityStatus,
    MissingField,
    PolicyDecision,
    ReturnReason,
    RiskReason,
)
from customer_service.rag.schemas import PolicyDocument


class EligibilityEngine:
    def __init__(self, config: EligibilityRuleConfig) -> None:
        self._config = config

    def evaluate(self, request: EligibilityRequest) -> EligibilityResult:
        return self._bind_result(self._evaluate(request), request=request)

    def _evaluate(self, request: EligibilityRequest) -> EligibilityResult:
        as_of = request.as_of or self._config.reference_date
        missing = self._missing_fields(request)
        if missing:
            return self._result(
                status=EligibilityStatus.NEEDS_INFORMATION,
                eligibility=EligibilityConclusion.INDETERMINATE,
                missing_fields=missing,
                message=f"信息不足，请补充：{', '.join(missing)}。",
            )

        assert request.item is not None
        assert request.return_reason is not None
        assert request.order.delivered_at is not None

        if not self._item_binds_to_order(request):
            return self._approval(
                risk_reasons=(RiskReason.EVIDENCE_MISMATCH,),
                message="商品事实无法绑定到已授权订单，需要人工确认。",
            )

        if request.order.status != self._config.eligible_order_status:
            return self._result(
                status=EligibilityStatus.INELIGIBLE,
                eligibility=EligibilityConclusion.INELIGIBLE,
                matched_rule_ids=("ORDER_STATUS_NOT_ELIGIBLE",),
                message="订单状态不符合当前退货判断条件。",
            )

        policies = self._matching_current_policies(request, as_of=as_of)
        if not policies:
            return self._approval(
                risk_reasons=(RiskReason.POLICY_EVIDENCE_INSUFFICIENT,),
                message="缺少当前适用政策依据，需要人工确认。",
            )
        if len(policies) != 1:
            decisions = {policy.decision for policy in policies}
            risk = (
                RiskReason.POLICY_CONFLICT
                if len(decisions) > 1
                else RiskReason.POLICY_EVIDENCE_INSUFFICIENT
            )
            return self._approval(
                risk_reasons=(risk,),
                policy_ids=tuple(policy.policy_id for policy in policies),
                message="政策证据存在冲突或无法确定优先级，需要人工确认。",
            )

        policy = policies[0]
        days = (as_of - request.order.delivered_at.date()).days
        if days < 0:
            return self._approval(
                risk_reasons=(RiskReason.EVIDENCE_MISMATCH,),
                policy_ids=(policy.policy_id,),
                message="订单日期事实异常，需要人工确认。",
            )

        risk_reasons: list[RiskReason] = []
        matched_rule_ids: list[str] = []
        if policy.return_window_days > 0 and days > policy.return_window_days:
            risk_reasons.append(RiskReason.OVERDUE_EXCEPTION)
            matched_rule_ids.append("RETURN_WINDOW_EXCEEDED")
        if self._config.is_high_value(
            currency=request.order.currency,
            total_amount=request.order.total_amount,
        ):
            risk_reasons.append(RiskReason.HIGH_VALUE_ORDER)
            matched_rule_ids.append("HIGH_VALUE_THRESHOLD")
        if risk_reasons:
            if len(risk_reasons) == 2:
                risk_message = "超过普通退货窗口且命中高金额规则，等待人工审批。"
            elif risk_reasons[0] is RiskReason.OVERDUE_EXCEPTION:
                risk_message = "超过普通退货窗口，作为超期特例等待人工审批。"
            else:
                risk_message = "命中高金额规则，等待人工审批。"
            return self._approval(
                risk_reasons=tuple(risk_reasons),
                policy_ids=(policy.policy_id,),
                matched_rule_ids=tuple(matched_rule_ids),
                days=days,
                message=risk_message,
            )

        decision_result = self._apply_policy_decision(
            request=request,
            policy=policy,
            days=days,
        )
        if decision_result is not None:
            return decision_result

        if policy.return_window_days <= 0:
            return self._approval(
                risk_reasons=(RiskReason.POLICY_EVIDENCE_INSUFFICIENT,),
                policy_ids=(policy.policy_id,),
                message="当前政策没有可用退货窗口，需要人工确认。",
            )

        if request.order.currency != self._config.high_value.currency:
            return self._approval(
                risk_reasons=(RiskReason.POLICY_EVIDENCE_INSUFFICIENT,),
                policy_ids=(policy.policy_id,),
                days=days,
                message="订单币种没有对应风险阈值，需要人工确认。",
            )

        if request.return_reason is ReturnReason.QUALITY_ISSUE:
            return self._result(
                status=EligibilityStatus.VERIFICATION_REQUIRED,
                eligibility=EligibilityConclusion.CONDITIONAL,
                policy_ids=(policy.policy_id,),
                matched_rule_ids=("QUALITY_RETURN_WINDOW", "ISSUE_VERIFICATION"),
                risk_reasons=(RiskReason.ISSUE_VERIFICATION_REQUIRED,),
                days=days,
                message="处于三十个自然日质量退货窗口，等待质量问题核验。",
            )

        if request.item_condition != self._config.resalable_item_condition:
            return self._result(
                status=EligibilityStatus.INELIGIBLE,
                eligibility=EligibilityConclusion.INELIGIBLE,
                policy_ids=(policy.policy_id,),
                matched_rule_ids=("ITEM_NOT_RESALABLE",),
                days=days,
                message="商品状态不满足普通退货的再次销售条件。",
            )

        boundary_rule = (
            "STANDARD_WINDOW_INCLUSIVE"
            if days == policy.return_window_days
            else "STANDARD_RETURN_ELIGIBLE"
        )
        message = (
            f"第七天仍在窗口内，符合条件（{policy.policy_id}）。"
            if days == policy.return_window_days
            else f"符合条件，适用政策 {policy.policy_id}，无需人工审批。"
        )
        return self._result(
            status=EligibilityStatus.ELIGIBLE,
            eligibility=EligibilityConclusion.ELIGIBLE,
            policy_ids=(policy.policy_id,),
            matched_rule_ids=(boundary_rule,),
            days=days,
            message=message,
        )

    def _bind_result(
        self, result: EligibilityResult, *, request: EligibilityRequest
    ) -> EligibilityResult:
        if request.item is None:
            return result
        return result.model_copy(
            update={
                "input_binding": EligibilityInputBinding(
                    order_id=request.order.order_id,
                    order_item_id=request.item.order_item_id,
                    product_id=request.item.product_id,
                    rule_version=self._config.rule_version,
                )
            }
        )

    @staticmethod
    def _missing_fields(request: EligibilityRequest) -> tuple[MissingField, ...]:
        missing: list[MissingField] = []
        if request.return_reason is None:
            missing.append(MissingField.RETURN_REASON)
        if request.item is None:
            missing.append(MissingField.TARGET_ITEM)
        if request.order.delivered_at is None:
            missing.append(MissingField.DELIVERED_AT)
        if request.return_reason is ReturnReason.CHANGED_MIND and not request.item_condition:
            missing.append(MissingField.ITEM_CONDITION)
        if request.return_reason is ReturnReason.QUALITY_ISSUE and not request.issue_code:
            missing.append(MissingField.ISSUE_CODE)
        return tuple(missing)

    @staticmethod
    def _item_binds_to_order(request: EligibilityRequest) -> bool:
        assert request.item is not None
        return any(
            item.order_item_id == request.item.order_item_id
            and item.product_id == request.item.product_id
            for item in request.order.items
        )

    def _apply_policy_decision(
        self,
        *,
        request: EligibilityRequest,
        policy: PolicyDocument,
        days: int,
    ) -> EligibilityResult | None:
        assert request.return_reason is not None
        if policy.decision == PolicyDecision.DENY:
            return self._result(
                status=EligibilityStatus.INELIGIBLE,
                eligibility=EligibilityConclusion.INELIGIBLE,
                policy_ids=(policy.policy_id,),
                matched_rule_ids=("POLICY_DENIES_RETURN",),
                days=days,
                message=f"当前适用政策 {policy.policy_id} 明确不允许该退货。",
            )

        supported_decisions = {
            PolicyDecision.ALLOW_IF_RESALABLE.value,
            PolicyDecision.ALLOW_AFTER_ISSUE_VERIFICATION.value,
        }
        if policy.decision not in supported_decisions:
            return self._approval(
                risk_reasons=(RiskReason.POLICY_EVIDENCE_INSUFFICIENT,),
                policy_ids=(policy.policy_id,),
                matched_rule_ids=("UNSUPPORTED_POLICY_DECISION",),
                days=days,
                message="政策决策语义不受支持，需要人工确认。",
            )

        expected_decision = {
            ReturnReason.CHANGED_MIND: PolicyDecision.ALLOW_IF_RESALABLE.value,
            ReturnReason.QUALITY_ISSUE: PolicyDecision.ALLOW_AFTER_ISSUE_VERIFICATION.value,
        }[request.return_reason]
        if policy.decision != expected_decision:
            return self._approval(
                risk_reasons=(RiskReason.POLICY_EVIDENCE_INSUFFICIENT,),
                policy_ids=(policy.policy_id,),
                matched_rule_ids=("POLICY_DECISION_MISMATCH",),
                days=days,
                message="退货原因与政策决策语义不匹配，需要人工确认。",
            )
        return None

    @staticmethod
    def _matching_current_policies(
        request: EligibilityRequest,
        *,
        as_of: date,
    ) -> tuple[PolicyDocument, ...]:
        assert request.item is not None
        assert request.return_reason is not None
        return tuple(
            policy
            for policy in request.policies
            if policy.is_current(as_of)
            and request.item.category in policy.applicable_categories
            and policy.return_reason == request.return_reason.value
        )

    def _approval(
        self,
        *,
        risk_reasons: tuple[RiskReason, ...],
        message: str,
        policy_ids: tuple[str, ...] = (),
        matched_rule_ids: tuple[str, ...] = (),
        days: int | None = None,
    ) -> EligibilityResult:
        return self._result(
            status=EligibilityStatus.REQUIRES_APPROVAL,
            eligibility=EligibilityConclusion.INDETERMINATE,
            policy_ids=policy_ids,
            matched_rule_ids=matched_rule_ids,
            risk_reasons=risk_reasons,
            requires_approval=True,
            days=days,
            message=message,
        )

    def _result(
        self,
        *,
        status: EligibilityStatus,
        eligibility: EligibilityConclusion,
        message: str,
        policy_ids: tuple[str, ...] = (),
        matched_rule_ids: tuple[str, ...] = (),
        missing_fields: tuple[MissingField, ...] = (),
        risk_reasons: tuple[RiskReason, ...] = (),
        requires_approval: bool = False,
        days: int | None = None,
    ) -> EligibilityResult:
        return EligibilityResult(
            rule_version=self._config.rule_version,
            status=status,
            eligibility=eligibility,
            applicable_policy_ids=policy_ids,
            matched_rule_ids=matched_rule_ids,
            missing_fields=missing_fields,
            risk_reasons=risk_reasons,
            requires_human_approval=requires_approval,
            days_since_delivery=days,
            message=message,
        )
