"""Validate DeepSeek/Fake plan candidates and route only permitted T-602 transitions."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from customer_service.agent_runtime.executor import ControlledAgentExecutor
from customer_service.agent_runtime.schemas import AgentReasonCode, AgentState
from customer_service.model_gateway.gateway import ModelGateway
from customer_service.model_gateway.schemas import (
    AgentPlanCandidate,
    ModelRequest,
    ModelResultStatus,
    ModelTask,
)


class AgentPlanOutcome(StrEnum):
    READY_FOR_VALIDATION = "ready_for_validation"
    CLARIFY = "clarify"
    ESCALATE = "escalate"
    FAILED_SAFE = "failed_safe"


class AgentPlanAudit(BaseModel):
    """Safe audit metadata: no prompt, raw model content, or reasoning is retained."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str | None = None
    intent: str | None = None
    requested_capability: str | None = None
    model_status: ModelResultStatus
    reason_code: AgentReasonCode


class AgentPlanResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: AgentState
    outcome: AgentPlanOutcome
    plan: AgentPlanCandidate | None = None
    audit: AgentPlanAudit


class AgentPlanService:
    """T-603 only: model proposes a plan; deterministic code decides whether it may advance."""

    _ALLOWED_CAPABILITIES = {
        "policy_question": {"policy.lookup", "clarify", "escalate"},
        "order_query": {"order.get_authorized", "clarify", "escalate"},
        "return_request": {"return.evaluate", "clarify", "escalate"},
        "unknown": {"clarify", "escalate"},
    }

    def __init__(self, *, executor: ControlledAgentExecutor, model_gateway: ModelGateway) -> None:
        self._executor = executor
        self._model_gateway = model_gateway

    def propose(self, state: AgentState, *, text: str, prompt_version: str) -> AgentPlanResult:
        request = ModelRequest(
            case_id=state.turn_id,
            task=ModelTask.AGENT_PLAN_GENERATION,
            text=text,
            prompt_version=prompt_version,
        )
        response = self._model_gateway.generate(request)
        if response.status is not ModelResultStatus.SUCCEEDED:
            code = (
                AgentReasonCode.PLAN_MODEL_INVALID
                if response.status is ModelResultStatus.INVALID_OUTPUT
                else AgentReasonCode.PLAN_MODEL_UNAVAILABLE
            )
            return self._failed(state, response.status, code)
        if not isinstance(response.output, AgentPlanCandidate):
            return self._failed(state, response.status, AgentReasonCode.PLAN_MODEL_INVALID)
        plan = response.output
        if not self._is_policy_valid(plan):
            return self._failed(state, response.status, AgentReasonCode.PLAN_POLICY_VIOLATION)
        audit = AgentPlanAudit(
            schema_version=plan.schema_version,
            intent=plan.intent,
            requested_capability=plan.requested_capability,
            model_status=response.status,
            reason_code=AgentReasonCode.PLAN_ACCEPTED,
        )
        if plan.requested_capability == "clarify":
            return AgentPlanResult(
                state=self._executor.route_plan_uncertainty(state, escalate=False),
                outcome=AgentPlanOutcome.CLARIFY,
                plan=plan,
                audit=audit.model_copy(
                    update={"reason_code": AgentReasonCode.PLAN_NEEDS_CLARIFICATION}
                ),
            )
        if plan.requested_capability == "escalate":
            return AgentPlanResult(
                state=self._executor.route_plan_uncertainty(state, escalate=True),
                outcome=AgentPlanOutcome.ESCALATE,
                plan=plan,
                audit=audit.model_copy(update={"reason_code": AgentReasonCode.PLAN_ESCALATED}),
            )
        return AgentPlanResult(
            state=self._executor.accept_validated_model_plan(state),
            outcome=AgentPlanOutcome.READY_FOR_VALIDATION,
            plan=plan,
            audit=audit,
        )

    def _failed(
        self, state: AgentState, model_status: ModelResultStatus, code: AgentReasonCode
    ) -> AgentPlanResult:
        return AgentPlanResult(
            state=self._executor.fail_model_plan(state, code),
            outcome=AgentPlanOutcome.FAILED_SAFE,
            audit=AgentPlanAudit(model_status=model_status, reason_code=code),
        )

    @classmethod
    def _is_policy_valid(cls, plan: AgentPlanCandidate) -> bool:
        if plan.requested_capability not in cls._ALLOWED_CAPABILITIES[plan.intent]:
            return False
        is_uncertain = plan.requested_capability in {"clarify", "escalate"}
        if is_uncertain:
            return plan.uncertainty_reason is not None
        return not plan.clarification_fields and plan.uncertainty_reason is None
