from customer_service.response_gate.schemas import (
    ResponseDraft,
    ResponseEvidenceContext,
    ResponseGateAction,
)
from customer_service.response_gate.service import ResponseGateService


def test_public_gate_never_returns_forged_completion() -> None:
    result = ResponseGateService().evaluate(
        ResponseDraft(message="申请已完成，编号 SC-FAKE-999。"),
        evidence=ResponseEvidenceContext(),
    )
    assert result.action is ResponseGateAction.CLARIFY
    assert result.response is None and "SC-FAKE-999" not in result.message
