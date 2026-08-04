from customer_service.agent_runtime.executor import (
    ControlledAgentExecutor,
    InMemoryTrustedApprovalEventAuthority,
)
from customer_service.agent_runtime.schemas import (
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
    DeterministicStep,
    TrustedApprovalEvent,
)


def _validated(executor: ControlledAgentExecutor) -> AgentState:
    state = executor.receive_turn(conversation_id="CONV-1", turn_id="TURN-1", user_id="USER-1")
    state = executor.apply_event(state, AgentEventType.USER_MESSAGE)
    state = executor.apply_event(state, AgentEventType.MODEL_RESULT)
    return executor.apply_event(state, AgentEventType.MODEL_RESULT)


def _waiting(executor: ControlledAgentExecutor) -> AgentState:
    return executor.execute(
        _validated(executor),
        DeterministicPlan(steps=(), final_action=DeterministicFinalAction.WAIT_APPROVAL),
    )


def _event(
    authority: InMemoryTrustedApprovalEventAuthority,
    binding: ApprovalBinding,
    decision: str,
    event_type: AgentEventType,
) -> TrustedApprovalEvent:
    return authority._issue_for_trusted_fixture(binding, decision, event_type)


def test_normal_transition_to_completed_has_complete_audit_fields() -> None:
    executor = ControlledAgentExecutor()
    state = executor.execute(
        _validated(executor),
        DeterministicPlan(
            steps=(DeterministicStep.READ_CONTEXT,), final_action=DeterministicFinalAction.DRAFT
        ),
    )
    state = executor.apply_event(state, AgentEventType.MODEL_RESULT)
    state = executor.complete_gate(state)
    audit = state.audit_events[-1]
    assert state.status is AgentStatus.COMPLETED
    assert (audit.from_status, audit.to_status, audit.event_type) == (
        AgentStatus.GATING,
        AgentStatus.COMPLETED,
        AgentEventType.TOOL_RESULT,
    )
    assert audit.reason_code is AgentReasonCode.TOOL_RESULT_ACCEPTED


def test_only_static_steps_are_accepted_and_duplicate_or_budget_fail_safely() -> None:
    executor = ControlledAgentExecutor(AgentExecutionPolicy(max_budget_units=1))
    duplicate = executor.execute(
        _validated(executor),
        DeterministicPlan(
            steps=(DeterministicStep.READ_CONTEXT, DeterministicStep.READ_CONTEXT),
            final_action=DeterministicFinalAction.DRAFT,
        ),
    )
    assert duplicate.reason_code is AgentReasonCode.DUPLICATE_STEP
    exhausted = executor.execute(
        _validated(executor),
        DeterministicPlan(
            steps=(DeterministicStep.READ_CONTEXT, DeterministicStep.PREPARE_DRAFT),
            final_action=DeterministicFinalAction.DRAFT,
        ),
    )
    assert exhausted.reason_code is AgentReasonCode.TOOL_BUDGET_EXCEEDED


def test_illegal_tool_timeout_and_fixed_failure_surrogate_safely_stop() -> None:
    executor = ControlledAgentExecutor()
    state = executor.receive_turn(conversation_id="CONV-1", turn_id="TURN-1", user_id="USER-1")
    assert executor.apply_event(state, AgentEventType.TOOL_RESULT).reason_code is (
        AgentReasonCode.ILLEGAL_TRANSITION
    )
    understanding = executor.apply_event(state, AgentEventType.USER_MESSAGE)
    assert executor.apply_event(understanding, AgentEventType.TIMEOUT).reason_code is (
        AgentReasonCode.MODEL_TIMEOUT
    )
    assert executor.simulate_execution_failure(_validated(executor)).reason_code is (
        AgentReasonCode.EXECUTION_FAILED
    )


def test_plan_limit_and_all_terminal_final_actions_are_bounded() -> None:
    executor = ControlledAgentExecutor(AgentExecutionPolicy(max_plan_rounds=1))
    limited = _validated(executor).model_copy(update={"plan_rounds": 1})
    assert (
        executor.execute(
            limited, DeterministicPlan(steps=(), final_action=DeterministicFinalAction.DRAFT)
        ).reason_code
        is AgentReasonCode.PLAN_LIMIT_EXCEEDED
    )
    for final_action, expected in (
        (DeterministicFinalAction.CLARIFY, AgentStatus.CLARIFYING),
        (DeterministicFinalAction.ESCALATE, AgentStatus.ESCALATING),
    ):
        assert (
            executor.execute(
                _validated(executor), DeterministicPlan(steps=(), final_action=final_action)
            ).status
            is expected
        )


def test_bare_approval_and_resume_events_cannot_be_used_to_progress() -> None:
    executor = ControlledAgentExecutor()
    waiting = _waiting(executor)
    assert (
        executor.apply_event(waiting, AgentEventType.USER_MESSAGE).status
        is AgentStatus.WAITING_APPROVAL
    )
    assert executor.apply_event(waiting, AgentEventType.APPROVAL_DECIDED).reason_code is (
        AgentReasonCode.UNTRUSTED_APPROVAL_EVENT
    )
    assert executor.apply_event(waiting, AgentEventType.RESUME_REQUESTED).reason_code is (
        AgentReasonCode.UNTRUSTED_APPROVAL_EVENT
    )


def test_trusted_event_requires_exact_binding_proof_and_supports_all_decisions() -> None:
    authority = InMemoryTrustedApprovalEventAuthority()
    executor = ControlledAgentExecutor(approval_events=authority)
    waiting = _waiting(executor)
    assert waiting.approval_binding is not None
    binding = waiting.approval_binding
    forged = TrustedApprovalEvent(
        binding=binding,
        decision="approved",
        event_type=AgentEventType.APPROVAL_DECIDED,
        sequence=1,
        proof="forged",
    )
    assert executor.record_trusted_approval(waiting, forged).reason_code is (
        AgentReasonCode.CHECKPOINT_BINDING_MISMATCH
    )
    for decision, expected in (
        ("approved", AgentStatus.EXECUTING),
        ("adjusted", AgentStatus.CLARIFYING),
        ("rejected", AgentStatus.DRAFTING),
    ):
        decided_event = _event(authority, binding, decision, AgentEventType.APPROVAL_DECIDED)
        resume_event = _event(authority, binding, decision, AgentEventType.RESUME_REQUESTED)
        assert executor.resume_from_trusted_approval(waiting, resume_event).reason_code is (
            AgentReasonCode.UNTRUSTED_APPROVAL_EVENT
        )
        decided = executor.record_trusted_approval(waiting, decided_event)
        assert decided.status is AgentStatus.WAITING_APPROVAL
        assert executor.resume_from_trusted_approval(decided, resume_event).status is expected


def test_cross_binding_and_checkpoint_conflict_are_safely_audited() -> None:
    authority = InMemoryTrustedApprovalEventAuthority()
    executor = ControlledAgentExecutor(approval_events=authority)
    waiting = _waiting(executor)
    assert waiting.approval_binding is not None
    other = ApprovalBinding(
        approval_id="APPROVAL-OTHER",
        workflow_id="WORKFLOW-OTHER",
        checkpoint_id="CHECKPOINT-OTHER",
        conversation_id="CONV-OTHER",
        user_id="USER-OTHER",
        version=1,
    )
    authority.register(other)
    cross = _event(authority, other, "approved", AgentEventType.RESUME_REQUESTED)
    assert executor.resume_from_trusted_approval(waiting, cross).reason_code is (
        AgentReasonCode.CHECKPOINT_BINDING_MISMATCH
    )
    for kind, code in (
        (CheckpointFailureKind.MISSING, AgentReasonCode.CHECKPOINT_MISSING),
        (CheckpointFailureKind.VERSION_MISMATCH, AgentReasonCode.CHECKPOINT_VERSION_MISMATCH),
        (CheckpointFailureKind.CAS_CONFLICT, AgentReasonCode.CHECKPOINT_CONFLICT),
        (CheckpointFailureKind.BINDING_MISMATCH, AgentReasonCode.CHECKPOINT_BINDING_MISMATCH),
    ):
        failed = executor.record_checkpoint_failure(waiting, CheckpointFailure(kind=kind))
        assert failed.status is AgentStatus.FAILED_SAFE
        assert failed.reason_code is code
        assert failed.audit_events[-1].event_type is AgentEventType.CHECKPOINT_CONFLICT
        assert failed.audit_events[-1].to_status is AgentStatus.FAILED_SAFE


def test_cancelled_completed_and_invalid_approval_decision_do_not_bypass_terminal_rules() -> None:
    executor = ControlledAgentExecutor()
    state = executor.receive_turn(conversation_id="CONV-1", turn_id="TURN-1", user_id="USER-1")
    completed = executor.apply_event(state, AgentEventType.CANCELLED)
    assert completed.status is AgentStatus.COMPLETED
    assert executor.apply_event(completed, AgentEventType.CANCELLED).reason_code is (
        AgentReasonCode.ILLEGAL_TRANSITION
    )
    waiting = _waiting(executor)
    assert waiting.approval_binding is not None
    event = TrustedApprovalEvent(
        binding=waiting.approval_binding,
        decision="invalid",
        event_type=AgentEventType.APPROVAL_DECIDED,
        sequence=1,
        proof="x",
    )
    assert executor.record_trusted_approval(waiting, event).reason_code is (
        AgentReasonCode.CHECKPOINT_BINDING_MISMATCH
    )


def test_decision_is_single_terminal_and_proofs_bind_decision_and_event_type() -> None:
    for first, second in (
        ("approved", "rejected"),
        ("adjusted", "approved"),
        ("rejected", "approved"),
    ):
        authority = InMemoryTrustedApprovalEventAuthority()
        executor = ControlledAgentExecutor(approval_events=authority)
        waiting = _waiting(executor)
        assert waiting.approval_binding is not None
        binding = waiting.approval_binding
        first_decision = _event(authority, binding, first, AgentEventType.APPROVAL_DECIDED)
        recorded = executor.record_trusted_approval(waiting, first_decision)
        second_decision = _event(authority, binding, second, AgentEventType.APPROVAL_DECIDED)
        rejected = executor.record_trusted_approval(recorded, second_decision)
        assert rejected.status is AgentStatus.WAITING_APPROVAL
        assert rejected.trusted_approval_decision == first
        assert rejected.reason_code is AgentReasonCode.APPROVAL_ALREADY_DECIDED
        assert rejected.audit_events[-1].to_status is AgentStatus.WAITING_APPROVAL
        resume = _event(authority, binding, first, AgentEventType.RESUME_REQUESTED)
        assert executor.resume_from_trusted_approval(rejected, resume).reason_code in {
            AgentReasonCode.RESUME_APPROVED,
            AgentReasonCode.RESUME_ADJUSTED,
            AgentReasonCode.RESUME_REJECTED,
        }

    authority = InMemoryTrustedApprovalEventAuthority()
    executor = ControlledAgentExecutor(approval_events=authority)
    waiting = _waiting(executor)
    assert waiting.approval_binding is not None
    original = _event(
        authority, waiting.approval_binding, "approved", AgentEventType.APPROVAL_DECIDED
    )
    altered_decision = original.model_copy(update={"decision": "rejected"})
    altered_type = original.model_copy(update={"event_type": AgentEventType.RESUME_REQUESTED})
    assert executor.record_trusted_approval(waiting, altered_decision).reason_code is (
        AgentReasonCode.CHECKPOINT_BINDING_MISMATCH
    )
    assert executor.record_trusted_approval(waiting, altered_type).reason_code is (
        AgentReasonCode.CHECKPOINT_BINDING_MISMATCH
    )
