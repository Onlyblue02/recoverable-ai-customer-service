"""Static allow-list. Definitions are contracts, not adapters and not executable callbacks."""

from customer_service.agent_runtime.schemas import AgentStatus
from customer_service.agent_tools.schemas import (
    ParameterSource,
    ToolContract,
    ToolEffect,
    ToolId,
)


class ToolRegistry:
    def __init__(self, contracts: tuple[ToolContract, ...] | None = None) -> None:
        selected = contracts or self._default_contracts()
        self._contracts = {contract.tool_id: contract for contract in selected}
        if len(self._contracts) != len(selected):
            raise ValueError("tool contract ids must be unique")

    def get(self, tool_id: str) -> ToolContract | None:
        try:
            return self._contracts.get(ToolId(tool_id))
        except ValueError:
            return None

    @staticmethod
    def _default_contracts() -> tuple[ToolContract, ...]:
        readable = (ParameterSource.USER_CANDIDATE, ParameterSource.CONFIRMED_FIELD)
        return (
            ToolContract(
                tool_id=ToolId.POLICY_LOOKUP,
                effect=ToolEffect.READ_ONLY,
                allowed_states=(AgentStatus.VALIDATING_PLAN,),
                model_parameter_names=(),
                required_parameter_names=(),
                allowed_sources=(),
                server_injected_fields=("user_id",),
                budget_cost=1,
                callable_by_model_plan=True,
            ),
            ToolContract(
                tool_id=ToolId.ORDER_GET_AUTHORIZED,
                effect=ToolEffect.READ_ONLY,
                allowed_states=(AgentStatus.VALIDATING_PLAN,),
                model_parameter_names=("order_id",),
                required_parameter_names=("order_id",),
                allowed_sources=readable,
                server_injected_fields=("user_id",),
                budget_cost=1,
                callable_by_model_plan=True,
            ),
            ToolContract(
                tool_id=ToolId.RETURN_EVALUATE,
                effect=ToolEffect.CONTROLLED_BUSINESS_REQUEST,
                allowed_states=(AgentStatus.VALIDATING_PLAN,),
                model_parameter_names=("order_id", "return_reason", "item_condition"),
                required_parameter_names=("order_id", "return_reason", "item_condition"),
                allowed_sources=readable,
                server_injected_fields=("user_id",),
                budget_cost=1,
                callable_by_model_plan=True,
            ),
            ToolContract(
                tool_id=ToolId.SERVICE_CASE_CREATE,
                effect=ToolEffect.CONTROLLED_BUSINESS_REQUEST,
                allowed_states=(AgentStatus.EXECUTING,),
                model_parameter_names=(),
                required_parameter_names=(),
                allowed_sources=(),
                server_injected_fields=("user_id", "idempotency_key"),
                budget_cost=2,
                callable_by_model_plan=False,
            ),
            *tuple(
                ToolContract(
                    tool_id=tool_id,
                    effect=ToolEffect.MODEL_FORBIDDEN_HIGH_RISK,
                    allowed_states=(),
                    model_parameter_names=(),
                    required_parameter_names=(),
                    allowed_sources=(),
                    server_injected_fields=("user_id", "workflow_id", "idempotency_key"),
                    budget_cost=2,
                    callable_by_model_plan=False,
                )
                for tool_id in (
                    ToolId.HIGH_RISK_START_OR_GET,
                    ToolId.HIGH_RISK_RESUME,
                    ToolId.APPROVAL_DECIDE,
                )
            ),
        )
