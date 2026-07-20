from collections.abc import Callable
from datetime import date

from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.schemas import (
    PolicyAnswerReason,
    PolicyAnswerResult,
    PolicyAnswerStatus,
    PolicyCitation,
    PolicyDocument,
    PolicyQuery,
    RecommendedAction,
)

PolicyAnswerAssembler = Callable[[PolicyDocument], PolicyAnswerResult]


class PolicyAnswerService:
    def __init__(
        self,
        catalog: PolicyCatalog,
        answer_assembler: PolicyAnswerAssembler | None = None,
    ) -> None:
        self._catalog = catalog
        self._answer_assembler = answer_assembler or self._assemble_answer

    def answer(self, query: PolicyQuery) -> PolicyAnswerResult:
        as_of = query.as_of or self._catalog.reference_date
        category_policies = self._catalog.for_category(query.category)
        if not category_policies:
            return self._insufficient(
                reason=PolicyAnswerReason.NO_RESULT,
                message="缺少政策依据；缺少依据时不能形成确定性结论。",
                candidates=(),
            )

        return_reason = query.return_reason
        if return_reason is None:
            reasons = {policy.return_reason for policy in category_policies}
            if len(reasons) != 1:
                return self._insufficient(
                    reason=PolicyAnswerReason.MISSING_RETURN_REASON,
                    message="缺少退货原因，无法确定当前适用政策。",
                    candidates=category_policies,
                )
            return_reason = next(iter(reasons))

        related = self._catalog.matching(
            category=query.category,
            return_reason=return_reason,
        )
        if not related:
            return self._insufficient(
                reason=PolicyAnswerReason.NO_RESULT,
                message="缺少政策依据；缺少依据时不能形成确定性结论。",
                candidates=category_policies,
            )

        current = tuple(policy for policy in related if policy.is_current(as_of))
        if not current:
            if all(policy.effective_to < as_of or policy.status == "expired" for policy in related):
                return self._insufficient(
                    reason=PolicyAnswerReason.EXPIRED_ONLY,
                    message="没有当前有效依据：匹配政策已过期。",
                    candidates=related,
                )
            return self._insufficient(
                reason=PolicyAnswerReason.NO_CURRENT_POLICY,
                message="没有当前有效依据：匹配政策当前未生效。",
                candidates=related,
            )

        if len({policy.decision for policy in current}) > 1:
            return PolicyAnswerResult(
                status=PolicyAnswerStatus.CONFLICT,
                action=RecommendedAction.ESCALATE,
                reason=PolicyAnswerReason.CONFLICTING_POLICIES,
                message="政策存在冲突，需要人工确认。",
                answer=None,
                citations=(),
                candidate_policy_ids=self._policy_ids(current),
            )

        if len(current) > 1:
            return self._insufficient(
                reason=PolicyAnswerReason.AMBIGUOUS_SOURCES,
                message="存在多份无法确定优先级的当前政策，需要人工确认。",
                candidates=current,
            )

        trusted_evidence = (current[0],)
        draft = self._answer_assembler(trusted_evidence[0])
        return self._bind_to_trusted_evidence(
            draft,
            trusted_evidence=trusted_evidence,
            as_of=as_of,
        )

    def _assemble_answer(self, policy: PolicyDocument) -> PolicyAnswerResult:
        answer = self._render_answer(policy)
        citation = self._citation_for(policy)
        return PolicyAnswerResult(
            status=PolicyAnswerStatus.ANSWERED,
            action=RecommendedAction.ANSWER,
            reason=PolicyAnswerReason.CURRENT_POLICY,
            message=answer,
            answer=answer,
            citations=(citation,),
            candidate_policy_ids=(policy.policy_id,),
        )

    def _bind_to_trusted_evidence(
        self,
        draft: PolicyAnswerResult,
        *,
        trusted_evidence: tuple[PolicyDocument, ...],
        as_of: date,
    ) -> PolicyAnswerResult:
        if not self._is_grounded(draft, trusted_evidence=trusted_evidence, as_of=as_of):
            return self._insufficient(
                reason=PolicyAnswerReason.UNGROUNDED_CITATION,
                message="政策引用无法绑定到本次检索证据，不能公开确定性答案。",
                candidates=trusted_evidence,
            )
        return draft

    def _is_grounded(
        self,
        draft: PolicyAnswerResult,
        *,
        trusted_evidence: tuple[PolicyDocument, ...],
        as_of: date,
    ) -> bool:
        if len(trusted_evidence) != 1:
            return False
        policy = trusted_evidence[0]
        if not policy.is_current(as_of):
            return False
        if (
            draft.status is not PolicyAnswerStatus.ANSWERED
            or draft.action is not RecommendedAction.ANSWER
            or draft.reason is not PolicyAnswerReason.CURRENT_POLICY
            or draft.answer != self._render_answer(policy)
            or draft.message != draft.answer
            or draft.candidate_policy_ids != (policy.policy_id,)
            or len(draft.citations) != 1
        ):
            return False

        return draft.citations[0] == self._citation_for(policy)

    @staticmethod
    def _render_answer(policy: PolicyDocument) -> str:
        answer = f"根据《{policy.title}》（{policy.policy_id}），{policy.content}"
        return answer

    @staticmethod
    def _citation_for(policy: PolicyDocument) -> PolicyCitation:
        return PolicyCitation(
            policy_id=policy.policy_id,
            evidence_id=policy.evidence_id,
            policy_version=policy.policy_version,
            title=policy.title,
            source=policy.source,
            effective_from=policy.effective_from,
            effective_to=policy.effective_to,
            excerpt=policy.content,
        )

    @staticmethod
    def _policy_ids(policies: tuple[PolicyDocument, ...]) -> tuple[str, ...]:
        return tuple(policy.policy_id for policy in policies)

    def _insufficient(
        self,
        *,
        reason: PolicyAnswerReason,
        message: str,
        candidates: tuple[PolicyDocument, ...],
    ) -> PolicyAnswerResult:
        return PolicyAnswerResult(
            status=PolicyAnswerStatus.INSUFFICIENT_EVIDENCE,
            action=RecommendedAction.CLARIFY,
            reason=reason,
            message=message,
            answer=None,
            citations=(),
            candidate_policy_ids=self._policy_ids(candidates),
        )
