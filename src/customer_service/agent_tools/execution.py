"""T-605 controlled business adapters.

No public data model is an execution capability: a step is usable exactly once only
when this process-local authority has signed and retained it after T-604 validation.
"""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from customer_service.agent_response.schemas import TrustedEvidenceSnapshot
from customer_service.agent_runtime.schemas import AgentState, AgentStatus
from customer_service.agent_tools.evidence import EvidenceVerifier, InMemoryEvidenceAuthority
from customer_service.agent_tools.schemas import (
    EvidencePublicField,
    EvidenceRecord,
    EvidenceScope,
    ExecutionPermit,
    ToolId,
    ToolResultStatus,
    TrustedExecutionReceipt,
    ValidatedToolStep,
)
from customer_service.approvals.service import ApprovalTaskService
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.eligibility.schemas import (
    EligibilityItemFacts,
    EligibilityRequest,
    EligibilityResult,
    ReturnReason,
)
from customer_service.orchestration.high_risk_schemas import (
    HighRiskContext,
    HighRiskStartRequest,
)
from customer_service.orchestration.high_risk_service import HighRiskReturnWorkflowService
from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.schemas import PolicyAnswerStatus, PolicyCitation, PolicyQuery
from customer_service.rag.service import PolicyAnswerService
from customer_service.recovery.schemas import RecoveryAccessContext
from customer_service.recovery.service import ApprovalRecoveryService
from customer_service.service_cases.schemas import (
    ServiceCaseAccessContext,
    ServiceCaseCreateRequest,
    ServiceCaseEligibilityContext,
)
from customer_service.service_cases.service import ServiceCaseService
from customer_service.tools.order_tool import OrderQueryService
from customer_service.tools.schemas import (
    AuthorizedOrderFacts,
    OrderAccessContext,
    OrderQuery,
    OrderQueryResult,
    OrderQueryStatus,
)


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    succeeded: bool
    code: str = Field(min_length=1)
    order: OrderQueryResult | None = None
    order_item_id: str | None = None
    eligibility_code: str | None = None
    policy_ids: tuple[str, ...] = ()
    evidence: EvidenceRecord | None = None
    continuations: tuple[ExecutionPermit, ...] = ()
    continuation_state: AgentState | None = None
    response_snapshot: TrustedEvidenceSnapshot | None = None


class PolicyContextProvider(Protocol):
    def get(self, *, conversation_id: str, turn_id: str, user_id: str) -> PolicyQuery | None: ...


class _ExecutionPermitAuthority:
    """Private one-shot issuer.  The signed payload is also kept server-side."""

    def __init__(self) -> None:
        self._secret = secrets.token_bytes(32)
        self._pending: dict[str, tuple[str, str, str, AgentStatus, ValidatedToolStep, str]] = {}

    def _issue(self, *, state: AgentState, step: ValidatedToolStep) -> ExecutionPermit:
        permit_id = secrets.token_urlsafe(18)
        proof = self._proof(permit_id, state, step)
        self._pending[permit_id] = (
            state.conversation_id,
            state.turn_id,
            state.user_id,
            state.status,
            step,
            proof,
        )
        return ExecutionPermit(
            permit_id=permit_id,
            conversation_id=state.conversation_id,
            turn_id=state.turn_id,
            user_id=state.user_id,
            step=step,
            proof=proof,
        )

    def consume(self, *, state: AgentState, permit: ExecutionPermit) -> ValidatedToolStep | None:
        pending = self._pending.get(permit.permit_id)
        if pending is None:
            return None
        conversation_id, turn_id, user_id, status, step, proof = pending
        if (conversation_id, turn_id, user_id, status, step, proof) != (
            state.conversation_id,
            state.turn_id,
            state.user_id,
            state.status,
            permit.step,
            permit.proof,
        ):
            return None
        expected = self._proof(permit.permit_id, state, permit.step)
        if not hmac.compare_digest(proof, expected):
            return None
        del self._pending[permit.permit_id]
        return step

    def _proof(self, permit_id: str, state: AgentState, step: ValidatedToolStep) -> str:
        payload = "|".join(
            (permit_id, state.conversation_id, state.turn_id, state.user_id, step.call_key)
        )
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()


class ExecutionPermitVerifier:
    """Consumer-only facade; it deliberately has no permit signing operation."""

    def __init__(self, authority: _ExecutionPermitAuthority, *, _token: object) -> None:
        if _token is not _VERIFIER_TOKEN:
            raise PermissionError("execution verifier is validator-owned")
        self._authority = authority

    def consume(self, *, state: AgentState, permit: ExecutionPermit) -> ValidatedToolStep | None:
        return self._authority.consume(state=state, permit=permit)


_VERIFIER_TOKEN = object()


def _verifier_for(authority: _ExecutionPermitAuthority) -> ExecutionPermitVerifier:
    return ExecutionPermitVerifier(authority, _token=_VERIFIER_TOKEN)


class ControlledToolExecutor:
    """Dispatches only a validator-issued step and injects every sensitive fact server-side."""

    def __init__(
        self,
        *,
        permits: ExecutionPermitVerifier,
        orders: OrderQueryService,
        policies: PolicyAnswerService,
        catalog: PolicyCatalog,
        product_categories: dict[str, str],
        eligibility: EligibilityEngine,
        high_risk: HighRiskReturnWorkflowService | None = None,
        recovery: ApprovalRecoveryService | None = None,
        approvals: ApprovalTaskService | None = None,
        service_cases: ServiceCaseService | None = None,
        policy_contexts: PolicyContextProvider | None = None,
    ) -> None:
        self._permits, self._orders, self._policies = permits, orders, policies
        self._continuation_permits = _ExecutionPermitAuthority()
        self._catalog, self._categories, self._eligibility = (
            catalog,
            product_categories,
            eligibility,
        )
        self._high_risk, self._recovery, self._approvals = high_risk, recovery, approvals
        self._service_cases = service_cases
        evidence_authority = InMemoryEvidenceAuthority()
        self.__evidence_verifier = EvidenceVerifier(evidence_authority)

        def issue_evidence(
            *,
            execution_id: str,
            conversation_id: str,
            turn_id: str,
            user_id: str,
            tool_id: ToolId,
            order_id: str | None,
            order_item_id: str | None,
            public_fields: tuple[EvidencePublicField, ...],
            result_status: ToolResultStatus,
            payload: TrustedEvidenceSnapshot | None,
        ) -> EvidenceRecord | None:
            """Closure-held capability; no authority method or constructor exposes it."""
            receipt = TrustedExecutionReceipt(
                execution_id=execution_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                user_id=user_id,
                tool_id=tool_id,
                contract_version="tool-contract-v1",
                result_status=result_status,
                scope=EvidenceScope.TURN,
                order_id=order_id,
                order_item_id=order_item_id,
                public_fields=(
                    public_fields if result_status is ToolResultStatus.SUCCEEDED else ()
                ),
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                proof="pending",
            )
            key = evidence_authority._receipt_key(receipt)
            proof = secrets.token_urlsafe(24)
            trusted = receipt.model_copy(update={"proof": proof})
            evidence_authority._receipt_proofs[key] = proof
            return evidence_authority.issue_from_trusted_receipt(trusted, payload=payload)

        self.__issue_evidence: Callable[..., EvidenceRecord | None] = issue_evidence
        self._policy_contexts = policy_contexts
        self._continuation_data: dict[
            str,
            tuple[
                AuthorizedOrderFacts,
                str,
                EligibilityResult,
                ReturnReason,
                str,
                tuple[PolicyCitation, ...],
            ],
        ] = {}
        self._workflow_data: dict[str, tuple[str, str]] = {}

    @property
    def evidence_verifier(self) -> EvidenceVerifier:
        """Expose verification only; this facade cannot create evidence or receipts."""
        return self.__evidence_verifier

    def execute(self, *, state: AgentState, permit: ExecutionPermit) -> ToolExecutionResult:
        step = self._permits.consume(state=state, permit=permit)
        if step is None:
            step = self._continuation_permits.consume(state=state, permit=permit)
        if step is None:
            return ToolExecutionResult(succeeded=False, code="EXECUTION_PERMIT_INVALID")
        values = {str(parameter.name): parameter.value for parameter in step.parameters}
        if step.tool_id is ToolId.ORDER_GET_AUTHORIZED:
            order = self._orders.query(
                OrderQuery(order_id=values["order_id"]),
                access_context=OrderAccessContext(current_user_id=state.user_id),
            )
            result = ToolExecutionResult(
                succeeded=order.status is OrderQueryStatus.FOUND,
                code="ORDER_FOUND"
                if order.status is OrderQueryStatus.FOUND
                else "ORDER_UNAVAILABLE",
                order=order,
                response_snapshot=(
                    TrustedEvidenceSnapshot(order=order.order) if order.order is not None else None
                ),
            )
            return self._with_evidence(state=state, step=step, result=result)
        if step.tool_id is ToolId.RETURN_EVALUATE:
            return self._with_evidence(
                state=state, step=step, result=self._evaluate(state=state, values=values)
            )
        if step.tool_id is ToolId.POLICY_LOOKUP:
            return self._lookup_policy(state=state, step=step)
        if step.tool_id is ToolId.SERVICE_CASE_CREATE:
            return self._create_low_risk(state=state, permit=permit, step=step)
        if step.tool_id is ToolId.HIGH_RISK_START_OR_GET:
            return self._start_high_risk(state=state, permit=permit, step=step)
        if step.tool_id is ToolId.APPROVAL_GET_STATUS:
            return self._approval_status(state=state, permit=permit, step=step)
        if step.tool_id is ToolId.HIGH_RISK_RESUME:
            return self._resume_high_risk(state=state, permit=permit, step=step)
        return ToolExecutionResult(succeeded=False, code="TOOL_NOT_EXECUTABLE_IN_T605")

    def _lookup_policy(self, *, state: AgentState, step: ValidatedToolStep) -> ToolExecutionResult:
        query = (
            None
            if self._policy_contexts is None
            else self._policy_contexts.get(
                conversation_id=state.conversation_id,
                turn_id=state.turn_id,
                user_id=state.user_id,
            )
        )
        if query is None:
            return ToolExecutionResult(succeeded=False, code="POLICY_CONTEXT_REQUIRED")
        answer = self._policies.answer(query)
        succeeded = answer.status is PolicyAnswerStatus.ANSWERED
        result = ToolExecutionResult(
            succeeded=succeeded,
            code=answer.status.value,
            policy_ids=answer.candidate_policy_ids if succeeded else (),
            response_snapshot=(
                TrustedEvidenceSnapshot(policy_citations=answer.citations) if succeeded else None
            ),
        )
        return self._with_evidence(state=state, step=step, result=result)

    def _with_evidence(
        self, *, state: AgentState, step: ValidatedToolStep, result: ToolExecutionResult
    ) -> ToolExecutionResult:
        order = result.order.order if result.order is not None else None
        fields: list[EvidencePublicField] = []
        if order is not None:
            fields.append(EvidencePublicField(name="order_id", value=order.order_id))
        if result.order_item_id is not None:
            fields.append(EvidencePublicField(name="order_item_id", value=result.order_item_id))
        if result.eligibility_code is not None:
            fields.append(
                EvidencePublicField(name="eligibility_code", value=result.eligibility_code)
            )
        for policy_id in result.policy_ids:
            fields.append(EvidencePublicField(name="policy_id", value=policy_id))
            policy = next(
                (item for item in self._catalog.policies if item.policy_id == policy_id),
                None,
            )
            if policy is not None:
                fields.append(
                    EvidencePublicField(name="policy_version", value=policy.policy_version)
                )
        record = self.__issue_evidence(
            execution_id=f"EXE-{step.call_key}",
            conversation_id=state.conversation_id,
            turn_id=state.turn_id,
            user_id=state.user_id,
            tool_id=step.tool_id,
            order_id=None if order is None else order.order_id,
            order_item_id=result.order_item_id,
            public_fields=tuple(fields),
            result_status=ToolResultStatus.SUCCEEDED
            if result.succeeded
            else ToolResultStatus.FAILED,
            payload=result.response_snapshot,
        )
        return result.model_copy(update={"evidence": record})

    def _evaluate(self, *, state: AgentState, values: dict[str, str]) -> ToolExecutionResult:
        order = self._orders.query(
            OrderQuery(order_id=values["order_id"]),
            access_context=OrderAccessContext(current_user_id=state.user_id),
        )
        if (
            order.status is not OrderQueryStatus.FOUND
            or order.order is None
            or len(order.order.items) != 1
        ):
            return ToolExecutionResult(succeeded=False, code="ORDER_UNAVAILABLE", order=order)
        item = order.order.items[0]
        category = self._categories.get(item.product_id)
        if category is None:
            return ToolExecutionResult(
                succeeded=False, code="POLICY_EVIDENCE_UNAVAILABLE", order=order
            )
        reason = ReturnReason(values["return_reason"])
        answer = self._policies.answer(PolicyQuery(category=category, return_reason=reason.value))
        # Only the exact catalog records selected by the grounded policy service are admissible.
        trusted = (
            tuple(
                policy
                for policy in self._catalog.policies
                if policy.policy_id in answer.candidate_policy_ids
            )
            if answer.status is PolicyAnswerStatus.ANSWERED
            else ()
        )
        decision = self._eligibility.evaluate(
            EligibilityRequest(
                order=order.order,
                item=EligibilityItemFacts(
                    order_item_id=item.order_item_id, product_id=item.product_id, category=category
                ),
                return_reason=reason,
                item_condition=values["item_condition"],
                issue_code="reported" if reason is ReturnReason.QUALITY_ISSUE else None,
                policies=trusted,
                as_of=date.today(),
            )
        )
        applicable_citations = tuple(
            citation
            for citation in answer.citations
            if citation.policy_id in decision.applicable_policy_ids
        )
        result = ToolExecutionResult(
            succeeded=True,
            code=decision.status.value,
            order=order,
            order_item_id=item.order_item_id,
            eligibility_code=decision.status.value,
            policy_ids=decision.applicable_policy_ids,
            response_snapshot=TrustedEvidenceSnapshot(
                policy_citations=applicable_citations,
                order=order.order,
                eligibility=decision,
            ),
        )
        if decision.status.value in {"eligible", "requires_approval"}:
            tool_id = (
                ToolId.SERVICE_CASE_CREATE
                if decision.status.value == "eligible"
                else ToolId.HIGH_RISK_START_OR_GET
            )
            continuation_state = state.model_copy(update={"status": AgentStatus.EXECUTING})
            continuation = self._continuation_permits._issue(
                state=continuation_state,
                step=ValidatedToolStep(
                    tool_id=tool_id,
                    contract_version="tool-contract-v1",
                    parameters=(),
                    budget_cost=2,
                    call_key=f"{tool_id}:{state.conversation_id}:{state.turn_id}",
                ),
            )
            self._continuation_data[continuation.permit_id] = (
                order.order,
                item.order_item_id,
                decision,
                reason,
                values["item_condition"],
                applicable_citations,
            )
            result = result.model_copy(
                update={
                    "continuations": (continuation,),
                    "continuation_state": continuation_state,
                }
            )
        return result

    def _create_low_risk(
        self, *, state: AgentState, permit: ExecutionPermit, step: ValidatedToolStep
    ) -> ToolExecutionResult:
        binding = self._continuation_data.pop(permit.permit_id, None)
        if self._service_cases is None or binding is None:
            return ToolExecutionResult(succeeded=False, code="LOW_RISK_CONTINUATION_INVALID")
        order, item_id, decision, _, _, citations = binding
        created = self._service_cases.create(
            ServiceCaseCreateRequest(order=order, order_item_id=item_id),
            access_context=ServiceCaseAccessContext(current_user_id=state.user_id),
            eligibility_context=ServiceCaseEligibilityContext(eligibility=decision),
        )
        succeeded = created.service_case is not None
        fields = (
            ()
            if created.service_case is None
            else (
                EvidencePublicField(
                    name="service_case_id", value=created.service_case.service_case_id
                ),
            )
        )
        record = self.__issue_evidence(
            execution_id=f"EXE-{step.call_key}",
            conversation_id=state.conversation_id,
            turn_id=state.turn_id,
            user_id=state.user_id,
            tool_id=step.tool_id,
            order_id=order.order_id,
            order_item_id=item_id,
            public_fields=fields,
            result_status=ToolResultStatus.SUCCEEDED if succeeded else ToolResultStatus.FAILED,
            payload=(
                None
                if created.service_case is None
                else TrustedEvidenceSnapshot(
                    policy_citations=tuple(citations),
                    order=order,
                    eligibility=decision,
                    service_case=created.service_case,
                )
            ),
        )
        return ToolExecutionResult(
            succeeded=succeeded,
            code=created.status.value,
            evidence=record,
        )

    def _start_high_risk(
        self, *, state: AgentState, permit: ExecutionPermit, step: ValidatedToolStep
    ) -> ToolExecutionResult:
        binding = self._continuation_data.pop(permit.permit_id, None)
        if self._high_risk is None or binding is None:
            return ToolExecutionResult(succeeded=False, code="HIGH_RISK_CONTINUATION_INVALID")
        order, _, decision, reason, item_condition, _ = binding
        started = self._high_risk.start(
            HighRiskStartRequest(message="受控高风险退货请求"),
            context=HighRiskContext(
                workflow_id=f"WF-{state.conversation_id}-{state.turn_id}",
                current_user_id=state.user_id,
                order_id=order.order_id,
                return_reason=reason,
                item_condition=item_condition,
            ),
        )
        succeeded = started.approval is not None
        record = self.__issue_evidence(
            execution_id=f"EXE-{step.call_key}",
            conversation_id=state.conversation_id,
            turn_id=state.turn_id,
            user_id=state.user_id,
            tool_id=step.tool_id,
            order_id=order.order_id,
            order_item_id=decision.input_binding.order_item_id if decision.input_binding else None,
            public_fields=()
            if started.approval is None
            else (EvidencePublicField(name="approval_id", value=started.approval.approval_id),),
            result_status=ToolResultStatus.SUCCEEDED if succeeded else ToolResultStatus.FAILED,
            payload=(
                None
                if started.approval is None
                else TrustedEvidenceSnapshot(
                    policy_citations=started.approval.policy_citations,
                    order=started.approval.order,
                    eligibility=started.approval.eligibility,
                    approval=started.approval,
                )
            ),
        )
        result = ToolExecutionResult(
            succeeded=succeeded, code=started.status.value, evidence=record
        )
        if started.approval is not None:
            continuation_state = state.model_copy(update={"status": AgentStatus.EXECUTING})
            permits = tuple(
                self._continuation_permits._issue(
                    state=continuation_state,
                    step=ValidatedToolStep(
                        tool_id=tool_id,
                        contract_version="tool-contract-v1",
                        parameters=(),
                        budget_cost=2,
                        call_key=f"{tool_id}:{state.conversation_id}:{state.turn_id}",
                    ),
                )
                for tool_id in (ToolId.APPROVAL_GET_STATUS, ToolId.HIGH_RISK_RESUME)
            )
            workflow_id = f"WF-{state.conversation_id}-{state.turn_id}"
            for continuation in permits:
                self._workflow_data[continuation.permit_id] = (
                    workflow_id,
                    started.approval.approval_id,
                )
            result = result.model_copy(
                update={"continuations": permits, "continuation_state": continuation_state}
            )
        return result

    def _approval_status(
        self, *, state: AgentState, permit: ExecutionPermit, step: ValidatedToolStep
    ) -> ToolExecutionResult:
        data = self._workflow_data.pop(permit.permit_id, None)
        if self._approvals is None or data is None:
            return ToolExecutionResult(succeeded=False, code="APPROVAL_CONTINUATION_INVALID")
        workflow_id, approval_id = data
        result = self._approvals.get_for_user(approval_id, current_user_id=state.user_id)
        succeeded = result.approval is not None
        record = self.__issue_evidence(
            execution_id=f"EXE-{step.call_key}",
            conversation_id=state.conversation_id,
            turn_id=state.turn_id,
            user_id=state.user_id,
            tool_id=step.tool_id,
            order_id=None if result.approval is None else result.approval.order.order_id,
            order_item_id=None if result.approval is None else result.approval.order_item_id,
            public_fields=()
            if result.approval is None
            else (EvidencePublicField(name="approval_id", value=result.approval.approval_id),),
            result_status=ToolResultStatus.SUCCEEDED if succeeded else ToolResultStatus.FAILED,
            payload=(
                None
                if result.approval is None
                else TrustedEvidenceSnapshot(
                    policy_citations=result.approval.policy_citations,
                    order=result.approval.order,
                    eligibility=result.approval.eligibility,
                    approval=result.approval,
                )
            ),
        )
        del workflow_id
        return ToolExecutionResult(succeeded=succeeded, code=result.status.value, evidence=record)

    def _resume_high_risk(
        self, *, state: AgentState, permit: ExecutionPermit, step: ValidatedToolStep
    ) -> ToolExecutionResult:
        data = self._workflow_data.pop(permit.permit_id, None)
        if self._recovery is None or data is None:
            return ToolExecutionResult(succeeded=False, code="RESUME_CONTINUATION_INVALID")
        workflow_id, _ = data
        result = self._recovery.recover(
            workflow_id, context=RecoveryAccessContext(current_user_id=state.user_id)
        )
        succeeded = result.stage.value in {
            "WAITING_APPROVAL",
            "NEEDS_CLARIFICATION",
            "REJECTED",
            "COMPLETED",
        }
        fields: tuple[EvidencePublicField, ...] = ()
        if result.service_case is not None:
            fields = (
                EvidencePublicField(
                    name="service_case_id", value=result.service_case.service_case_id
                ),
            )
        record = self.__issue_evidence(
            execution_id=f"EXE-{step.call_key}",
            conversation_id=state.conversation_id,
            turn_id=state.turn_id,
            user_id=state.user_id,
            tool_id=step.tool_id,
            order_id=None if result.approval is None else result.approval.order.order_id,
            order_item_id=None if result.approval is None else result.approval.order_item_id,
            public_fields=fields,
            result_status=ToolResultStatus.SUCCEEDED if succeeded else ToolResultStatus.FAILED,
            payload=(
                None
                if result.approval is None
                else TrustedEvidenceSnapshot(
                    policy_citations=result.approval.policy_citations,
                    order=result.approval.order,
                    eligibility=result.approval.eligibility,
                    approval=result.approval,
                    service_case=result.service_case,
                )
            ),
        )
        return ToolExecutionResult(succeeded=succeeded, code=result.stage.value, evidence=record)
