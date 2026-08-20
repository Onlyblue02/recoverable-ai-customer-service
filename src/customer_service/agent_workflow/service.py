"""The single controlled T-602 through T-606 Agent MVP composition path."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from customer_service.agent_planning.service import AgentPlanOutcome, AgentPlanService
from customer_service.agent_response.schemas import AgentResponseOutcome
from customer_service.agent_response.service import AgentResponseService
from customer_service.agent_runtime.executor import (
    ControlledAgentExecutor,
    InMemoryTrustedApprovalEventAuthority,
)
from customer_service.agent_runtime.schemas import (
    AgentEventType,
    AgentState,
    AgentStatus,
    ApprovalBinding,
)
from customer_service.agent_tools.execution import (
    ControlledToolExecutor,
    PolicyContextProvider,
    ToolExecutionResult,
)
from customer_service.agent_tools.schemas import (
    EvidenceRecord,
    ExecutionPermit,
    ParameterSource,
    PlanValidationContext,
    ToolId,
    TrustedParameter,
)
from customer_service.agent_tools.validator import ToolPlanOutcome, ToolPlanValidator
from customer_service.approvals.schemas import ApprovalStatus, ApprovalTaskSummary
from customer_service.approvals.service import ApprovalTaskService
from customer_service.eligibility.engine import EligibilityEngine
from customer_service.model_gateway.gateway import ModelGateway
from customer_service.orchestration.high_risk_service import HighRiskReturnWorkflowService
from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.service import PolicyAnswerService
from customer_service.recovery.service import ApprovalRecoveryService
from customer_service.response_gate.schemas import ResponseGateAction
from customer_service.response_gate.service import ResponseGateService
from customer_service.service_cases.service import ServiceCaseService
from customer_service.tools.order_tool import OrderQueryService
from customer_service.tools.schemas import AuthorizedOrderFacts


class AgentWorkflowOutcome(StrEnum):
    ALLOWED = "allowed"
    SAFE_REWRITE = "safe_rewrite"
    CLARIFY = "clarify"
    ESCALATE = "escalate"
    WAITING_APPROVAL = "waiting_approval"
    FAILED_SAFE = "failed_safe"


class AgentWorkflowRequest(BaseModel):
    """Public input contains language only, never identity or execution artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(min_length=1, max_length=4000)


class TrustedAgentContext(BaseModel):
    """Server-injected identity and previously confirmed conversational fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    confirmed_order_id: str | None = None
    confirmed_return_reason: str | None = None
    confirmed_item_condition: str | None = None

    def validation_context(self) -> PlanValidationContext:
        values = (
            ("order_id", self.confirmed_order_id),
            ("return_reason", self.confirmed_return_reason),
            ("item_condition", self.confirmed_item_condition),
        )
        return PlanValidationContext(
            authorized_user_id=self.user_id,
            trusted_parameters=tuple(
                TrustedParameter(
                    name=name,  # type: ignore[arg-type]
                    value=value,
                    source=ParameterSource.CONFIRMED_FIELD,
                )
                for name, value in values
                if value is not None
            ),
        )


class AgentWorkflowResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: AgentState
    outcome: AgentWorkflowOutcome
    public_response: str | None = None
    evidence_ids: tuple[str, ...] = ()
    policy_ids: tuple[str, ...] = ()
    authorized_order: AuthorizedOrderFacts | None = None
    approval_id: str | None = None
    gate_action: ResponseGateAction | None = None
    gate_reasons: tuple[str, ...] = ()
    reason_code: str = Field(min_length=1)


class _PendingApproval:
    def __init__(
        self,
        *,
        state: AgentState,
        status_permit: ExecutionPermit,
        resume_permit: ExecutionPermit,
        tool_state: AgentState,
        evidence: tuple[EvidenceRecord, ...],
        message: str,
    ) -> None:
        self.state = state
        self.status_permit = status_permit
        self.resume_permit = resume_permit
        self.tool_state = tool_state
        self.evidence = evidence
        self.message = message


class _TrustedApprovalTransitionAdapter:
    """Translate only server-read approval facts into proof-bound T-602 events."""

    def __init__(
        self,
        *,
        executor: ControlledAgentExecutor,
        authority: InMemoryTrustedApprovalEventAuthority,
        approvals: ApprovalTaskService | None,
    ) -> None:
        self._executor = executor
        self._authority = authority
        self._approvals = approvals

    def begin_wait(
        self, state: AgentState, *, approval_id: str, approval_version: int
    ) -> AgentState:
        binding = ApprovalBinding(
            approval_id=approval_id,
            workflow_id=f"WF-{state.conversation_id}-{state.turn_id}",
            checkpoint_id=f"CHECKPOINT-WF-{state.conversation_id}-{state.turn_id}",
            conversation_id=state.conversation_id,
            user_id=state.user_id,
            version=approval_version,
        )
        return self._executor.enter_waiting_approval(state, binding)

    def terminal_summary(self, state: AgentState) -> ApprovalTaskSummary | None:
        binding = state.approval_binding
        if self._approvals is None or binding is None:
            return None
        result = self._approvals.get_for_user(binding.approval_id, current_user_id=state.user_id)
        approval = result.approval
        if (
            approval is None
            or approval.status is ApprovalStatus.PENDING
            or approval.approval_id != binding.approval_id
            or approval.user_id != binding.user_id
            or binding.conversation_id != state.conversation_id
            or binding.workflow_id != f"WF-{state.conversation_id}-{state.turn_id}"
            or binding.checkpoint_id != f"CHECKPOINT-WF-{state.conversation_id}-{state.turn_id}"
            or approval.version != binding.version + 1
        ):
            return None
        return approval

    def transition(self, state: AgentState, approval: ApprovalTaskSummary) -> AgentState:
        binding = state.approval_binding
        if binding is None:
            return self._executor.fail_controlled_execution(state)
        decision = approval.status.value
        decided = self._authority._issue_from_verified_service(
            binding, decision, AgentEventType.APPROVAL_DECIDED
        )
        recorded = self._executor.record_trusted_approval(state, decided)
        if recorded.status is AgentStatus.FAILED_SAFE:
            return recorded
        resume = self._authority._issue_from_verified_service(
            binding, decision, AgentEventType.RESUME_REQUESTED
        )
        return self._executor.resume_from_trusted_approval(recorded, resume)


class AgentWorkflowService:
    """Own all permits/evidence and expose only start/resume with trusted context."""

    PLAN_PROMPT_VERSION = "t607-agent-workflow-plan-v1"
    RESPONSE_PROMPT_VERSION = "t607-agent-workflow-response-v1"

    def __init__(
        self,
        *,
        model_gateway: ModelGateway,
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
        gate: ResponseGateService | None = None,
    ) -> None:
        approval_events = InMemoryTrustedApprovalEventAuthority()
        executor = ControlledAgentExecutor(approval_events=approval_events)
        validator = ToolPlanValidator(executor=executor)
        tools = ControlledToolExecutor(
            permits=validator.execution_verifier,
            orders=orders,
            policies=policies,
            catalog=catalog,
            product_categories=product_categories,
            eligibility=eligibility,
            high_risk=high_risk,
            recovery=recovery,
            approvals=approvals,
            service_cases=service_cases,
            policy_contexts=policy_contexts,
        )
        self.__executor = executor
        self.__planner = AgentPlanService(executor=executor, model_gateway=model_gateway)
        self.__validator = validator
        self.__tools = tools
        self.__responses = AgentResponseService(
            executor=executor,
            model_gateway=model_gateway,
            evidence_verifier=tools.evidence_verifier,
            gate=gate,
        )
        self.__approvals = approvals
        self.__approval_transitions = _TrustedApprovalTransitionAdapter(
            executor=executor, authority=approval_events, approvals=approvals
        )
        self.__completed: dict[tuple[str, str, str], AgentWorkflowResult] = {}
        self.__pending: dict[tuple[str, str, str], _PendingApproval] = {}

    def handle(
        self, request: AgentWorkflowRequest, *, context: TrustedAgentContext
    ) -> AgentWorkflowResult:
        key = self._key(context)
        if key in self.__completed:
            return self.__completed[key]
        if key in self.__pending:
            return self._waiting(self.__pending[key])
        state = self.__executor.receive_turn(
            conversation_id=context.conversation_id,
            turn_id=context.turn_id,
            user_id=context.user_id,
        )
        state = self.__executor.apply_event(state, AgentEventType.USER_MESSAGE)
        state = self.__executor.apply_event(state, AgentEventType.MODEL_RESULT)
        planned = self.__planner.propose(
            state, text=request.message, prompt_version=self.PLAN_PROMPT_VERSION
        )
        if planned.outcome is not AgentPlanOutcome.READY_FOR_VALIDATION or planned.plan is None:
            return self._terminal_from_plan(planned.state, planned.outcome)
        validated = self.__validator.validate(
            planned.state, planned.plan, context.validation_context()
        )
        if validated.outcome is not ToolPlanOutcome.VALIDATED or validated.permit is None:
            return self._terminal(validated.state)
        executed = self.__tools.execute(state=validated.state, permit=validated.permit)
        if not executed.succeeded:
            return self._execution_failed(validated.state, executed.code)
        evidence = self._append_evidence((), executed)
        if not executed.continuations:
            executing = self.__executor.start_controlled_execution(validated.state)
            return self._draft_and_gate(key, executing, request.message, evidence)
        continuation_state = executed.continuation_state
        if continuation_state is None:
            return self._execution_failed(validated.state, "CONTINUATION_STATE_MISSING")
        continued = self.__tools.execute(state=continuation_state, permit=executed.continuations[0])
        if not continued.succeeded:
            return self._execution_failed(continuation_state, continued.code)
        evidence = self._append_evidence(evidence, continued)
        if executed.continuations[0].step.tool_id is ToolId.HIGH_RISK_START_OR_GET:
            resume = next(
                (
                    permit
                    for permit in continued.continuations
                    if permit.step.tool_id is ToolId.HIGH_RISK_RESUME
                ),
                None,
            )
            status_permit = next(
                (
                    permit
                    for permit in continued.continuations
                    if permit.step.tool_id is ToolId.APPROVAL_GET_STATUS
                ),
                None,
            )
            approval_id = self._approval_id(evidence)
            approval = (
                None
                if self.__approvals is None or approval_id is None
                else self.__approvals.get_for_user(
                    approval_id, current_user_id=context.user_id
                ).approval
            )
            approval_version = None if approval is None else approval.version
            if (
                resume is None
                or status_permit is None
                or continued.continuation_state is None
                or approval_id is None
                or approval_version is None
            ):
                return self._execution_failed(continuation_state, "RESUME_PERMIT_MISSING")
            waiting_state = self.__approval_transitions.begin_wait(
                continued.continuation_state,
                approval_id=approval_id,
                approval_version=approval_version,
            )
            pending = _PendingApproval(
                state=waiting_state,
                status_permit=status_permit,
                resume_permit=resume,
                tool_state=continued.continuation_state,
                evidence=evidence,
                message=request.message,
            )
            self.__pending[key] = pending
            return self._waiting(pending)
        return self._draft_and_gate(key, continuation_state, request.message, evidence)

    def resume(self, *, context: TrustedAgentContext) -> AgentWorkflowResult:
        key = self._key(context)
        if key in self.__completed:
            return self.__completed[key]
        pending = self.__pending.get(key)
        if pending is None:
            state = self.__executor.receive_turn(
                conversation_id=context.conversation_id,
                turn_id=context.turn_id,
                user_id=context.user_id,
            )
            failed = self.__executor.fail_controlled_execution(state)
            return AgentWorkflowResult(
                state=failed,
                outcome=AgentWorkflowOutcome.FAILED_SAFE,
                reason_code="PENDING_WORKFLOW_NOT_FOUND",
            )
        approval = self.__approval_transitions.terminal_summary(pending.state)
        if approval is None:
            return self._waiting(pending)
        status_result = self.__tools.execute(state=pending.tool_state, permit=pending.status_permit)
        if not status_result.succeeded:
            del self.__pending[key]
            return self._execution_failed(pending.state, status_result.code)
        evidence = self._append_evidence(
            tuple(
                record
                for record in pending.evidence
                if record.tool_id is not ToolId.HIGH_RISK_START_OR_GET
            ),
            status_result,
        )
        transitioned = self.__approval_transitions.transition(pending.state, approval)
        if transitioned.status is AgentStatus.FAILED_SAFE:
            del self.__pending[key]
            return self._terminal(transitioned)
        if transitioned.status is AgentStatus.CLARIFYING:
            del self.__pending[key]
            return AgentWorkflowResult(
                state=transitioned,
                outcome=AgentWorkflowOutcome.CLARIFY,
                evidence_ids=tuple(record.evidence_id for record in evidence),
                reason_code=transitioned.reason_code.value,
            )
        if transitioned.status is AgentStatus.DRAFTING:
            del self.__pending[key]
            return self._draft_and_gate(key, transitioned, pending.message, evidence)
        if transitioned.status is not AgentStatus.EXECUTING:
            del self.__pending[key]
            return self._execution_failed(transitioned, "RESUME_STATE_INVALID")
        resumed = self.__tools.execute(state=transitioned, permit=pending.resume_permit)
        if not resumed.succeeded:
            del self.__pending[key]
            return self._execution_failed(transitioned, resumed.code)
        evidence = self._append_evidence(evidence, resumed)
        del self.__pending[key]
        return self._draft_and_gate(key, transitioned, pending.message, evidence)

    def _draft_and_gate(
        self,
        key: tuple[str, str, str],
        state: AgentState,
        message: str,
        evidence: tuple[EvidenceRecord, ...],
    ) -> AgentWorkflowResult:
        drafting = (
            state
            if state.status is AgentStatus.DRAFTING
            else self.__executor.finish_controlled_execution(state)
        )
        response = self.__responses.generate(
            drafting,
            text=message,
            evidence=evidence,
            prompt_version=self.RESPONSE_PROMPT_VERSION,
        )
        result = AgentWorkflowResult(
            state=response.state,
            outcome=AgentWorkflowOutcome(response.outcome.value),
            public_response=response.public_response,
            evidence_ids=tuple(record.evidence_id for record in evidence),
            policy_ids=tuple(
                dict.fromkeys(
                    field.value
                    for record in evidence
                    for field in record.public_fields
                    if field.name == "policy_id"
                )
            ),
            authorized_order=(
                None
                if response.gate is None or response.gate.response is None
                else response.gate.response.order
            ),
            gate_action=None if response.gate is None else response.gate.action,
            gate_reasons=(
                ()
                if response.gate is None
                else tuple(reason.value for reason in response.gate.reasons)
            ),
            reason_code=response.state.reason_code.value,
        )
        if response.outcome in {AgentResponseOutcome.ALLOWED, AgentResponseOutcome.SAFE_REWRITE}:
            self.__completed[key] = result
        return result

    def _execution_failed(self, state: AgentState, code: str) -> AgentWorkflowResult:
        failed = self.__executor.fail_controlled_execution(state)
        return AgentWorkflowResult(
            state=failed, outcome=AgentWorkflowOutcome.FAILED_SAFE, reason_code=code
        )

    @staticmethod
    def _append_evidence(
        current: tuple[EvidenceRecord, ...], result: ToolExecutionResult
    ) -> tuple[EvidenceRecord, ...]:
        return current if result.evidence is None else (*current, result.evidence)

    @staticmethod
    def _terminal(state: AgentState) -> AgentWorkflowResult:
        outcomes = {
            AgentStatus.CLARIFYING: AgentWorkflowOutcome.CLARIFY,
            AgentStatus.ESCALATING: AgentWorkflowOutcome.ESCALATE,
        }
        return AgentWorkflowResult(
            state=state,
            outcome=outcomes.get(state.status, AgentWorkflowOutcome.FAILED_SAFE),
            reason_code=state.reason_code.value,
        )

    @staticmethod
    def _terminal_from_plan(state: AgentState, outcome: AgentPlanOutcome) -> AgentWorkflowResult:
        mapped = {
            AgentPlanOutcome.CLARIFY: AgentWorkflowOutcome.CLARIFY,
            AgentPlanOutcome.ESCALATE: AgentWorkflowOutcome.ESCALATE,
            AgentPlanOutcome.FAILED_SAFE: AgentWorkflowOutcome.FAILED_SAFE,
        }
        return AgentWorkflowResult(
            state=state,
            outcome=mapped.get(outcome, AgentWorkflowOutcome.FAILED_SAFE),
            reason_code=state.reason_code.value,
        )

    @staticmethod
    def _waiting(pending: _PendingApproval) -> AgentWorkflowResult:
        approval_id = AgentWorkflowService._approval_id(pending.evidence)
        return AgentWorkflowResult(
            state=pending.state,
            outcome=AgentWorkflowOutcome.WAITING_APPROVAL,
            evidence_ids=tuple(record.evidence_id for record in pending.evidence),
            approval_id=approval_id,
            reason_code="WAITING_APPROVAL",
        )

    @staticmethod
    def _approval_id(evidence: tuple[EvidenceRecord, ...]) -> str | None:
        return next(
            (
                field.value
                for record in evidence
                for field in record.public_fields
                if field.name == "approval_id"
            ),
            None,
        )

    @staticmethod
    def _key(context: TrustedAgentContext) -> tuple[str, str, str]:
        return context.conversation_id, context.turn_id, context.user_id
