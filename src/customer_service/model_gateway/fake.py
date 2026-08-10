from collections.abc import Mapping
from typing import Any

from customer_service.model_gateway.schemas import (
    AgentPlanCandidate,
    AgentResponseDraftCandidate,
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
        try:
            output = self._parse_output(request.task, payload)
            if isinstance(output, AgentResponseDraftCandidate):
                trusted_ids = {evidence.evidence_id for evidence in request.evidence}
                referenced = {
                    evidence_id for claim in output.claims for evidence_id in claim.evidence_ids
                }
                if not referenced.issubset(trusted_ids):
                    raise ValueError("response references unknown evidence")
        except ValueError:
            return ModelResponse(
                status=ModelResultStatus.INVALID_OUTPUT,
                task=request.task,
                output=None,
                error_code="FAKE_INVALID_STRUCTURED_OUTPUT",
                message="模型候选不符合受限结构，已安全降级。",
            )
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
        if request.task is ModelTask.AGENT_PLAN_GENERATION:
            return {
                "schema_version": "agent-plan-v1",
                "intent": "unknown",
                "requested_capability": "clarify",
                "extracted_parameters": {},
                "clarification_fields": ["order_id"],
                "uncertainty_reason": "ambiguous_intent",
            }
        if request.task is ModelTask.AGENT_RESPONSE_DRAFT_GENERATION:
            return {
                "schema_version": "agent-response-draft-v1",
                "text": "已根据本轮可信证据整理处理结果。",
                "claims": [
                    {
                        "claim_type": "policy",
                        "evidence_ids": [request.evidence[0].evidence_id],
                    }
                ],
            }
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
        if task is ModelTask.AGENT_PLAN_GENERATION:
            return AgentPlanCandidate.model_validate(payload)
        if task is ModelTask.AGENT_RESPONSE_DRAFT_GENERATION:
            return AgentResponseDraftCandidate.model_validate(payload)
        return GroundedResponseDraft.model_validate(payload)
