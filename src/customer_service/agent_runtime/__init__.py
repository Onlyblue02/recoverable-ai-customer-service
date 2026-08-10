"""T-602 Agent runtime package with cycle-safe lazy compatibility exports."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from customer_service.agent_runtime.executor import ControlledAgentExecutor
    from customer_service.agent_runtime.schemas import AgentState, AgentStatus

__all__ = ["AgentState", "AgentStatus", "ControlledAgentExecutor"]


def __getattr__(name: str) -> Any:
    """Preserve T-602 package imports without eager executor/evidence loading."""
    modules = {
        "AgentState": "customer_service.agent_runtime.schemas",
        "AgentStatus": "customer_service.agent_runtime.schemas",
        "ControlledAgentExecutor": "customer_service.agent_runtime.executor",
    }
    module_name = modules.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(module_name), name)
