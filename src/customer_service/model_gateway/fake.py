from collections.abc import Mapping
from typing import Any

from customer_service.model_gateway.schemas import (
    CorrectionCandidate,
    GroundedResponseDraft,
    IntentCandidate,
    ModelOutput,
    ModelRequest,
    ModelResponse,
    ModelResultStatus,
    ModelTask,
    ReturnFieldCandidate,
)


class FakeModelGateway:
    """Deterministic test double. It never reads configuration or calls a network."""

    def __init__(self, outputs: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self._outputs = dict(outputs or {})

    def generate(self, request: ModelRequest) -> ModelResponse:
        payload = self._outputs.get(request.case_id, self._default_payload(request))
        output = self._parse_output(request.task, payload)
        return ModelResponse(
            status=ModelResultStatus.SUCCEEDED,
            task=request.task,
            output=output,
            error_code=None,
            message="模型候选已生成，仍须由确定性服务验证。",
        )

    @staticmethod
    def _default_payload(request: ModelRequest) -> Mapping[str, Any]:
        if request.task is ModelTask.INTENT_CLASSIFICATION:
            return {"intent": "unknown"}
        if request.task is ModelTask.RETURN_FIELD_EXTRACTION:
            return {"order_id": None, "return_reason": None, "item_condition": None}
        if request.task is ModelTask.CORRECTION_RECOGNITION:
            return {"corrected_slot": None, "corrected_value": None}
        return {
            "text": "请以提供的政策证据为准。",
            "evidence_ids": [request.evidence[0].evidence_id],
        }

    @staticmethod
    def _parse_output(task: ModelTask, payload: Mapping[str, Any]) -> ModelOutput:
        if task is ModelTask.INTENT_CLASSIFICATION:
            return IntentCandidate.model_validate(payload)
        if task is ModelTask.RETURN_FIELD_EXTRACTION:
            return ReturnFieldCandidate.model_validate(payload)
        if task is ModelTask.CORRECTION_RECOGNITION:
            return CorrectionCandidate.model_validate(payload)
        return GroundedResponseDraft.model_validate(payload)
