"""Deterministic plan validation; this module has no imports of business tool adapters."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from customer_service.agent_runtime.executor import ControlledAgentExecutor
from customer_service.agent_runtime.schemas import AgentReasonCode, AgentState
from customer_service.agent_tools.registry import ToolRegistry
from customer_service.agent_tools.schemas import PlanValidationContext, ValidatedToolStep
from customer_service.model_gateway.schemas import AgentPlanCandidate


class ToolPlanOutcome(StrEnum):
    VALIDATED = "validated"
    CLARIFY = "clarify"
    FAILED_SAFE = "failed_safe"


class ToolPlanValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: AgentState
    outcome: ToolPlanOutcome
    step: ValidatedToolStep | None = None
    reason_code: AgentReasonCode


class ToolPlanValidator:
    def __init__(
        self, *, executor: ControlledAgentExecutor, registry: ToolRegistry | None = None
    ) -> None:
        self._executor = executor
        self._registry = registry or ToolRegistry()

    def validate(
        self, state: AgentState, plan: AgentPlanCandidate, context: PlanValidationContext
    ) -> ToolPlanValidationResult:
        if context.authorized_user_id != state.user_id:
            return self._failed(state, AgentReasonCode.TOOL_PERMISSION_DENIED)
        contract = self._registry.get(plan.requested_capability)
        if contract is None:
            return self._failed(state, AgentReasonCode.TOOL_NOT_REGISTERED)
        if (
            not contract.callable_by_model_plan
            or contract.effect.value == "model_forbidden_high_risk"
        ):
            return self._failed(state, AgentReasonCode.TOOL_FORBIDDEN)
        if state.status not in contract.allowed_states:
            return self._failed(state, AgentReasonCode.TOOL_STATE_NOT_ALLOWED)
        params: list[tuple[Literal["order_id", "return_reason", "item_condition"], str]] = []
        if plan.extracted_parameters.order_id is not None:
            params.append(("order_id", plan.extracted_parameters.order_id))
        if plan.extracted_parameters.return_reason is not None:
            params.append(("return_reason", plan.extracted_parameters.return_reason))
        if plan.extracted_parameters.item_condition is not None:
            params.append(("item_condition", plan.extracted_parameters.item_condition))
        names = tuple(name for name, _ in params)
        if any(name not in contract.model_parameter_names for name in names):
            return self._failed(state, AgentReasonCode.TOOL_PARAMETER_INVALID)
        missing = set(contract.required_parameter_names) - set(names)
        if missing:
            return ToolPlanValidationResult(
                state=self._executor.clarify_plan_validation(state),
                outcome=ToolPlanOutcome.CLARIFY,
                reason_code=AgentReasonCode.PLAN_CLARIFICATION_REQUIRED,
            )
        trusted_by_name = {item.name: item for item in context.trusted_parameters}
        trusted = []
        for name, value in params:
            source = trusted_by_name.get(name)
            if (
                source is None
                or source.value != value
                or source.source not in contract.allowed_sources
            ):
                return self._failed(state, AgentReasonCode.TOOL_PARAMETER_SOURCE_UNTRUSTED)
            trusted.append(source)
        call_key = f"{contract.tool_id}:{'|'.join(f'{item.name}={item.value}' for item in trusted)}"
        if call_key in context.executed_call_keys:
            return self._failed(state, AgentReasonCode.TOOL_DUPLICATE_CALL)
        if state.budget_used + contract.budget_cost > self._executor.policy.max_budget_units:
            return self._failed(state, AgentReasonCode.TOOL_BUDGET_EXCEEDED)
        step = ValidatedToolStep(
            tool_id=contract.tool_id,
            contract_version=contract.version,
            parameters=tuple(trusted),
            budget_cost=contract.budget_cost,
            call_key=call_key,
        )
        return ToolPlanValidationResult(
            state=self._executor.record_plan_validation(state),
            outcome=ToolPlanOutcome.VALIDATED,
            step=step,
            reason_code=AgentReasonCode.PLAN_VALIDATED,
        )

    def _failed(self, state: AgentState, code: AgentReasonCode) -> ToolPlanValidationResult:
        return ToolPlanValidationResult(
            state=self._executor.fail_plan_validation(state, code),
            outcome=ToolPlanOutcome.FAILED_SAFE,
            reason_code=code,
        )
