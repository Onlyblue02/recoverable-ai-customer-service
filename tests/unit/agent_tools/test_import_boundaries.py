"""Import-order regressions for the T-605 tool boundary."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module",
    (
        "customer_service.agent_tools.evidence",
        "customer_service.agent_tools.execution",
        "customer_service.agent_tools.validator",
        "customer_service.agent_runtime",
    ),
)
def test_module_imports_in_fresh_process(module: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_agent_runtime_lazy_exports_remain_compatible_in_fresh_process() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from customer_service.agent_runtime import "
            "AgentState, AgentStatus, ControlledAgentExecutor",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
