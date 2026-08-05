"""Explicit transition enforcement for T-602; no model or business tools are invoked."""

import secrets

from customer_service.agent_runtime.schemas import (
    AgentAuditEvent,
    AgentEventType,
    AgentExecutionPolicy,
    AgentReasonCode,
    AgentState,
    AgentStatus,
    ApprovalBinding,
    CheckpointFailure,
    CheckpointFailureKind,
    DeterministicFinalAction,
    DeterministicPlan,
    TrustedApprovalEvent,
)
from customer_service.agent_tools.evidence import (
    EvidenceAuthority,
    EvidenceVerifier,
    InMemoryEvidenceAuthority,
)
from customer_service.agent_tools.schemas import EvidenceRecord, TrustedExecutionReceipt


class InMemoryTrustedApprovalEventAuthority:
    """T-602 test authority; T-605 must replace it with trusted service adapters."""

    def __init__(self) -> None:
        self._proofs: dict[tuple[ApprovalBinding, str, AgentEventType, int], str] = {}

    def register(self, binding: ApprovalBinding) -> None:
        """Reserve a server-side binding; it does not expose a proof."""

        del binding

    def verify(self, event: TrustedApprovalEvent) -> bool:
        key = (event.binding, event.decision, event.event_type, event.sequence)
        return secrets.compare_digest(self._proofs.get(key, ""), event.proof)

    def _issue_for_trusted_fixture(
        self,
        binding: ApprovalBinding,
        decision: str,
        event_type: AgentEventType,
        sequence: int = 1,
    ) -> TrustedApprovalEvent:
        """Private fixture hook; production callers do not construct approval events."""

        key = (binding, decision, event_type, sequence)
        proof = secrets.token_urlsafe(24)
        self._proofs[key] = proof
        return TrustedApprovalEvent(
            binding=binding,
            decision=decision,
            event_type=event_type,
            sequence=sequence,
            proof=proof,
        )


class ControlledAgentExecutor:
    """Finite state machine. Its only steps are static no-op placeholders."""

    _MODEL_TRANSITIONS = {
        AgentStatus.UNDERSTANDING: AgentStatus.PLANNING,
        AgentStatus.PLANNING: AgentStatus.VALIDATING_PLAN,
        AgentStatus.DRAFTING: AgentStatus.GATING,
    }

    def __init__(
        self,
        policy: AgentExecutionPolicy | None = None,
        *,
        approval_events: InMemoryTrustedApprovalEventAuthority | None = None,
    ) -> None:
        self._policy = policy or AgentExecutionPolicy()
        self._approval_events = approval_events or InMemoryTrustedApprovalEventAuthority()
        self._evidence_authority: EvidenceAuthority = InMemoryEvidenceAuthority()

    @property
    def policy(self) -> AgentExecutionPolicy:
        """Read-only policy exposure for deterministic validation; it grants no execution."""
        return self._policy

    @property
    def evidence_authority(self) -> EvidenceVerifier:
        """Public verification only; receipt registration is not exposed at runtime."""
        return EvidenceVerifier(self._evidence_authority)

    def receive_turn(self, *, conversation_id: str, turn_id: str, user_id: str) -> AgentState:
        return AgentState(
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_id=user_id,
            status=AgentStatus.RECEIVED,
            reason_code=AgentReasonCode.TURN_ACCEPTED,
        )

    def apply_event(self, state: AgentState, event: AgentEventType) -> AgentState:
        if event is AgentEventType.USER_MESSAGE:
            if state.status is AgentStatus.RECEIVED:
                return self._move(
                    state, event, AgentStatus.UNDERSTANDING, AgentReasonCode.TURN_ACCEPTED
                )
            if state.status is AgentStatus.WAITING_APPROVAL:
                return self._move(
                    state,
                    event,
                    AgentStatus.WAITING_APPROVAL,
                    AgentReasonCode.APPROVAL_STILL_PENDING,
                )
            return self._illegal(state, event)
        if event is AgentEventType.MODEL_RESULT:
            target = self._MODEL_TRANSITIONS.get(state.status)
            return (
                self._move(state, event, target, AgentReasonCode.MODEL_RESULT_ACCEPTED)
                if target is not None
                else self._illegal(state, event)
            )
        if event is AgentEventType.TOOL_RESULT:
            return self._tool_result(state)
        if event in {AgentEventType.APPROVAL_DECIDED, AgentEventType.RESUME_REQUESTED}:
            return self._failed(state, event, AgentReasonCode.UNTRUSTED_APPROVAL_EVENT)
        if event is AgentEventType.TIMEOUT:
            return self._timeout(state)
        if event is AgentEventType.CANCELLED:
            if state.status is AgentStatus.WAITING_APPROVAL:
                return self._move(
                    state,
                    event,
                    AgentStatus.WAITING_APPROVAL,
                    AgentReasonCode.CANCELLATION_NOT_APPLICABLE,
                )
            if state.status is AgentStatus.COMPLETED:
                return self._illegal(state, event)
            return self._move(state, event, AgentStatus.COMPLETED, AgentReasonCode.TURN_CANCELLED)
        if event is AgentEventType.CHECKPOINT_CONFLICT:
            return self._move(
                state, event, AgentStatus.FAILED_SAFE, AgentReasonCode.CHECKPOINT_CONFLICT
            )
        return self._illegal(state, event)

    def execute(self, state: AgentState, plan: DeterministicPlan) -> AgentState:
        """Run only static no-op steps after deterministic plan-bound validation."""
        if state.status is not AgentStatus.VALIDATING_PLAN:
            return self._illegal(state, AgentEventType.TOOL_RESULT)
        if state.plan_rounds >= self._policy.max_plan_rounds:
            return self._failed(
                state, AgentEventType.TOOL_RESULT, AgentReasonCode.PLAN_LIMIT_EXCEEDED
            )
        if len(plan.steps) != len(set(plan.steps)):
            return self._failed(state, AgentEventType.TOOL_RESULT, AgentReasonCode.DUPLICATE_STEP)
        if state.budget_used + len(plan.steps) > self._policy.max_budget_units:
            return self._failed(
                state, AgentEventType.TOOL_RESULT, AgentReasonCode.TOOL_BUDGET_EXCEEDED
            )
        current = self._move(
            state.model_copy(update={"plan_rounds": state.plan_rounds + 1}),
            AgentEventType.TOOL_RESULT,
            AgentStatus.EXECUTING,
            AgentReasonCode.TOOL_RESULT_ACCEPTED,
        )
        for step in plan.steps:
            current = current.model_copy(
                update={
                    "budget_used": current.budget_used + 1,
                    "executed_steps": (*current.executed_steps, step),
                }
            )
        targets = {
            DeterministicFinalAction.DRAFT: AgentStatus.DRAFTING,
            DeterministicFinalAction.CLARIFY: AgentStatus.CLARIFYING,
            DeterministicFinalAction.ESCALATE: AgentStatus.ESCALATING,
            DeterministicFinalAction.WAIT_APPROVAL: AgentStatus.WAITING_APPROVAL,
        }
        if plan.final_action is DeterministicFinalAction.WAIT_APPROVAL:
            binding = ApprovalBinding(
                approval_id=f"APPROVAL-{state.conversation_id}-{state.turn_id}",
                workflow_id=f"WORKFLOW-{state.conversation_id}-{state.turn_id}",
                checkpoint_id=f"CHECKPOINT-{state.conversation_id}-{state.turn_id}",
                conversation_id=state.conversation_id,
                user_id=state.user_id,
                version=state.plan_rounds + 1,
            )
            self._approval_events.register(binding)
            current = current.model_copy(update={"approval_binding": binding})
        return self._move(
            current,
            AgentEventType.TOOL_RESULT,
            targets[plan.final_action],
            AgentReasonCode.TOOL_RESULT_ACCEPTED,
        )

    def accept_validated_model_plan(self, state: AgentState) -> AgentState:
        """Advance a schema- and policy-validated T-603 plan; never invoke a capability."""
        if state.status is not AgentStatus.PLANNING:
            return self._illegal(state, AgentEventType.MODEL_RESULT)
        return self._move(
            state,
            AgentEventType.MODEL_RESULT,
            AgentStatus.VALIDATING_PLAN,
            AgentReasonCode.PLAN_ACCEPTED,
        )

    def route_plan_uncertainty(self, state: AgentState, *, escalate: bool) -> AgentState:
        """Route an already validated non-executable plan without invoking any capability."""
        if state.status is not AgentStatus.PLANNING:
            return self._illegal(state, AgentEventType.MODEL_RESULT)
        target = AgentStatus.ESCALATING if escalate else AgentStatus.CLARIFYING
        code = (
            AgentReasonCode.PLAN_ESCALATED if escalate else AgentReasonCode.PLAN_NEEDS_CLARIFICATION
        )
        return self._move(state, AgentEventType.MODEL_RESULT, target, code)

    def fail_model_plan(self, state: AgentState, code: AgentReasonCode) -> AgentState:
        """Failure-only entry for T-603 validation results."""
        allowed = {
            AgentReasonCode.PLAN_MODEL_INVALID,
            AgentReasonCode.PLAN_MODEL_UNAVAILABLE,
            AgentReasonCode.PLAN_POLICY_VIOLATION,
        }
        if state.status is not AgentStatus.PLANNING or code not in allowed:
            return self._illegal(state, AgentEventType.MODEL_RESULT)
        return self._failed(state, AgentEventType.MODEL_RESULT, code)

    def record_plan_validation(self, state: AgentState) -> AgentState:
        """Record T-604 validation only; T-605 alone may execute an approved step."""
        if state.status is not AgentStatus.VALIDATING_PLAN:
            return self._illegal(state, AgentEventType.MODEL_RESULT)
        return self._move(
            state,
            AgentEventType.MODEL_RESULT,
            AgentStatus.VALIDATING_PLAN,
            AgentReasonCode.PLAN_VALIDATED,
        )

    def issue_evidence_from_trusted_receipt(
        self, receipt: TrustedExecutionReceipt
    ) -> EvidenceRecord | None:
        """T-604's sole public path: issuance needs an authority-verified execution receipt."""
        return self._evidence_authority.issue_from_trusted_receipt(receipt)

    def clarify_plan_validation(self, state: AgentState) -> AgentState:
        if state.status is not AgentStatus.VALIDATING_PLAN:
            return self._illegal(state, AgentEventType.MODEL_RESULT)
        return self._move(
            state,
            AgentEventType.MODEL_RESULT,
            AgentStatus.CLARIFYING,
            AgentReasonCode.PLAN_CLARIFICATION_REQUIRED,
        )

    def fail_plan_validation(self, state: AgentState, code: AgentReasonCode) -> AgentState:
        allowed = {
            AgentReasonCode.TOOL_NOT_REGISTERED,
            AgentReasonCode.TOOL_FORBIDDEN,
            AgentReasonCode.TOOL_STATE_NOT_ALLOWED,
            AgentReasonCode.TOOL_PARAMETER_INVALID,
            AgentReasonCode.TOOL_PARAMETER_SOURCE_UNTRUSTED,
            AgentReasonCode.TOOL_PERMISSION_DENIED,
            AgentReasonCode.TOOL_DUPLICATE_CALL,
            AgentReasonCode.TOOL_BUDGET_EXCEEDED,
        }
        if state.status is not AgentStatus.VALIDATING_PLAN or code not in allowed:
            return self._illegal(state, AgentEventType.MODEL_RESULT)
        return self._failed(state, AgentEventType.MODEL_RESULT, code)

    def record_trusted_approval(self, state: AgentState, event: TrustedApprovalEvent) -> AgentState:
        """Record one immutable human decision after source and binding validation."""
        if state.trusted_approval_decision is not None:
            return self._reject_without_transition(
                state, AgentEventType.APPROVAL_DECIDED, AgentReasonCode.APPROVAL_ALREADY_DECIDED
            )
        if not self._verified_binding(state, event, AgentEventType.APPROVAL_DECIDED):
            return self._failed(
                state,
                AgentEventType.APPROVAL_DECIDED,
                AgentReasonCode.CHECKPOINT_BINDING_MISMATCH,
            )
        codes = {
            "approved": AgentReasonCode.APPROVAL_APPROVED,
            "adjusted": AgentReasonCode.APPROVAL_ADJUSTED,
            "rejected": AgentReasonCode.APPROVAL_REJECTED,
        }
        code = codes.get(event.decision)
        if code is None:
            return self._failed(
                state, AgentEventType.APPROVAL_DECIDED, AgentReasonCode.UNTRUSTED_APPROVAL_EVENT
            )
        decided = state.model_copy(update={"trusted_approval_decision": event.decision})
        return self._move(decided, AgentEventType.APPROVAL_DECIDED, decided.status, code)

    def record_checkpoint_failure(
        self, state: AgentState, failure: CheckpointFailure
    ) -> AgentState:
        """Classify checkpoint failure before any possible recovery operation."""
        codes = {
            CheckpointFailureKind.MISSING: AgentReasonCode.CHECKPOINT_MISSING,
            CheckpointFailureKind.VERSION_MISMATCH: AgentReasonCode.CHECKPOINT_VERSION_MISMATCH,
            CheckpointFailureKind.CAS_CONFLICT: AgentReasonCode.CHECKPOINT_CONFLICT,
            CheckpointFailureKind.BINDING_MISMATCH: AgentReasonCode.CHECKPOINT_BINDING_MISMATCH,
        }
        return self._failed(state, AgentEventType.CHECKPOINT_CONFLICT, codes[failure.kind])

    def resume_from_trusted_approval(
        self, state: AgentState, event: TrustedApprovalEvent
    ) -> AgentState:
        """Resume only with a separately authenticated event for the recorded decision."""
        if not self._verified_binding(state, event, AgentEventType.RESUME_REQUESTED):
            return self._failed(
                state,
                AgentEventType.RESUME_REQUESTED,
                AgentReasonCode.CHECKPOINT_BINDING_MISMATCH,
            )
        if state.trusted_approval_decision != event.decision:
            return self._failed(
                state,
                AgentEventType.RESUME_REQUESTED,
                AgentReasonCode.UNTRUSTED_APPROVAL_EVENT,
            )
        targets = {
            "approved": (AgentStatus.EXECUTING, AgentReasonCode.RESUME_APPROVED),
            "adjusted": (AgentStatus.CLARIFYING, AgentReasonCode.RESUME_ADJUSTED),
            "rejected": (AgentStatus.DRAFTING, AgentReasonCode.RESUME_REJECTED),
        }
        target = targets.get(event.decision)
        if target is None:
            return self._failed(
                state, AgentEventType.RESUME_REQUESTED, AgentReasonCode.UNTRUSTED_APPROVAL_EVENT
            )
        status, code = target
        return self._move(state, AgentEventType.RESUME_REQUESTED, status, code)

    def simulate_execution_failure(self, state: AgentState) -> AgentState:
        """Fixed no-op failure surrogate; it never invokes caller-provided code."""
        if state.status is not AgentStatus.VALIDATING_PLAN:
            return self._illegal(state, AgentEventType.TOOL_RESULT)
        executing = self._move(
            state,
            AgentEventType.TOOL_RESULT,
            AgentStatus.EXECUTING,
            AgentReasonCode.TOOL_RESULT_ACCEPTED,
        )
        return self._failed(executing, AgentEventType.TOOL_RESULT, AgentReasonCode.EXECUTION_FAILED)

    def complete_gate(self, state: AgentState) -> AgentState:
        if state.status is not AgentStatus.GATING:
            return self._illegal(state, AgentEventType.TOOL_RESULT)
        return self._move(
            state,
            AgentEventType.TOOL_RESULT,
            AgentStatus.COMPLETED,
            AgentReasonCode.TOOL_RESULT_ACCEPTED,
        )

    def _tool_result(self, state: AgentState) -> AgentState:
        if state.status is AgentStatus.EXECUTING:
            return self._move(
                state,
                AgentEventType.TOOL_RESULT,
                AgentStatus.EXECUTING,
                AgentReasonCode.TOOL_RESULT_ACCEPTED,
            )
        return self._illegal(state, AgentEventType.TOOL_RESULT)

    def _timeout(self, state: AgentState) -> AgentState:
        if state.status in {AgentStatus.UNDERSTANDING, AgentStatus.PLANNING, AgentStatus.DRAFTING}:
            return self._failed(state, AgentEventType.TIMEOUT, AgentReasonCode.MODEL_TIMEOUT)
        if state.status is AgentStatus.EXECUTING:
            return self._failed(state, AgentEventType.TIMEOUT, AgentReasonCode.TOOL_TIMEOUT)
        return self._illegal(state, AgentEventType.TIMEOUT)

    def _verified_binding(
        self, state: AgentState, event: TrustedApprovalEvent, expected_type: AgentEventType
    ) -> bool:
        binding = state.approval_binding
        return (
            state.status is AgentStatus.WAITING_APPROVAL
            and binding is not None
            and binding == event.binding
            and binding.conversation_id == state.conversation_id
            and binding.user_id == state.user_id
            and event.event_type is expected_type
            and event.sequence == 1
            and self._approval_events.verify(event)
        )

    def _reject_without_transition(
        self, state: AgentState, event: AgentEventType, code: AgentReasonCode
    ) -> AgentState:
        return self._move(state, event, state.status, code)

    def _illegal(self, state: AgentState, event: AgentEventType) -> AgentState:
        return self._failed(state, event, AgentReasonCode.ILLEGAL_TRANSITION)

    def _failed(
        self, state: AgentState, event: AgentEventType, code: AgentReasonCode
    ) -> AgentState:
        return self._move(state, event, AgentStatus.FAILED_SAFE, code)

    @staticmethod
    def _move(
        state: AgentState, event: AgentEventType, target: AgentStatus, code: AgentReasonCode
    ) -> AgentState:
        audit = AgentAuditEvent(
            event_type=event,
            from_status=state.status,
            to_status=target,
            reason_code=code,
        )
        return state.model_copy(
            update={
                "status": target,
                "reason_code": code,
                "audit_events": (*state.audit_events, audit),
            }
        )
