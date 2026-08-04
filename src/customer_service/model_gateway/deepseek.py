import json
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from customer_service.infrastructure.config.settings import DeepSeekSettings
from customer_service.model_gateway.schemas import (
    AgentPlanCandidate,
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


class DeepSeekModelGateway:
    """OpenAI-compatible DeepSeek adapter with one bounded JSON repair attempt."""

    def __init__(self, settings: DeepSeekSettings, *, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.deepseek_timeout_seconds)

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not self._settings.is_configured:
            return self._failed(
                request.task,
                ModelResultStatus.UNAVAILABLE,
                "DEEPSEEK_NOT_CONFIGURED",
                "未配置 DeepSeek 模型，请设置 DEEPSEEK_API_KEY 与 DEEPSEEK_MODEL。",
            )

        for attempt in range(2):
            content = self._call(request, repair=attempt == 1)
            if content is None:
                return self._failed(
                    request.task,
                    ModelResultStatus.PROVIDER_FAILURE,
                    "DEEPSEEK_PROVIDER_UNAVAILABLE",
                    "模型服务暂不可用，已安全降级。",
                )
            output = self._parse(request, content)
            if output is not None:
                return ModelResponse(
                    status=ModelResultStatus.SUCCEEDED,
                    task=request.task,
                    output=output,
                    error_code=None,
                    message="模型候选已生成，仍须由确定性服务验证。",
                )
        return self._failed(
            request.task,
            ModelResultStatus.INVALID_OUTPUT,
            "DEEPSEEK_INVALID_STRUCTURED_OUTPUT",
            "模型输出不符合受限结构，已安全降级。",
        )

    def _call(self, request: ModelRequest, *, repair: bool) -> str | None:
        assert self._settings.deepseek_api_key is not None
        assert self._settings.deepseek_model is not None
        system = (
            "只输出一个 json 对象，不得添加 markdown、解释或额外字段。"
            "不得决定订单归属、退货资格、风险、审批、售后申请或质量门禁。"
            f"本任务的唯一合法 json 结构是：{self._json_contract(request.task)}"
        )
        if repair:
            system += "上一输出无效。仅修复为上述合法 json 结构。"
        payload = {
            "model": self._settings.deepseek_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(self._wire_request(request))},
            ],
        }
        try:
            response = self._client.post(
                f"{self._settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": (
                        f"Bearer {self._settings.deepseek_api_key.get_secret_value()}"
                    )
                },
                json=payload,
            )
            response.raise_for_status()
            document = response.json()
            return str(document["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _json_contract(task: ModelTask) -> str:
        contracts = {
            ModelTask.INTENT_CLASSIFICATION: (
                '{"intent":"policy_question|order_query|return_request|unknown"}'
            ),
            ModelTask.RETURN_FIELD_EXTRACTION: (
                '{"order_id":"string|null","return_reason":"changed_mind|quality_issue|null",'
                '"item_condition":"resalable|not_resalable|null"}'
            ),
            ModelTask.CORRECTION_RECOGNITION: (
                '{"corrected_slot":"return_reason|item_condition|null",'
                '"corrected_value":"changed_mind|quality_issue|resalable|not_resalable|null"}'
            ),
            ModelTask.GROUNDED_RESPONSE_GENERATION: (
                '{"text":"string","evidence_ids":["only ids from provided evidence"]}'
            ),
            ModelTask.AGENT_PLAN_GENERATION: (
                '{"schema_version":"agent-plan-v1","intent":"policy_question|order_query|return_request|unknown",'
                '"requested_capability":"policy.lookup|order.get_authorized|return.evaluate|clarify|escalate",'
                '"extracted_parameters":{"order_id":"string|null","return_reason":"changed_mind|quality_issue|null",'
                '"item_condition":"resalable|not_resalable|null"},'
                '"clarification_fields":["order_id|return_reason|item_condition"],'
                '"uncertainty_reason":"ambiguous_intent|missing_information|unsupported_request|low_confidence|null"}'
            ),
        }
        return contracts[task]

    @staticmethod
    def _wire_request(request: ModelRequest) -> Mapping[str, Any]:
        return {
            "task": request.task.value,
            "text": request.text,
            "prompt_version": request.prompt_version,
            "evidence": [evidence.model_dump() for evidence in request.evidence],
        }

    @staticmethod
    def _parse(request: ModelRequest, content: str) -> ModelOutput | None:
        try:
            payload = json.loads(content)
            if not isinstance(payload, dict):
                return None
            output = DeepSeekModelGateway._parse_for_task(request.task, payload)
            if isinstance(output, GroundedResponseDraft):
                trusted_ids = {evidence.evidence_id for evidence in request.evidence}
                if not set(output.evidence_ids).issubset(trusted_ids):
                    return None
            return output
        except (json.JSONDecodeError, ValidationError, TypeError):
            return None

    @staticmethod
    def _parse_for_task(task: ModelTask, payload: Mapping[str, Any]) -> ModelOutput:
        if task is ModelTask.INTENT_CLASSIFICATION:
            return IntentCandidate.model_validate(payload)
        if task is ModelTask.RETURN_FIELD_EXTRACTION:
            return ReturnFieldCandidate.model_validate(payload)
        if task is ModelTask.CORRECTION_RECOGNITION:
            return CorrectionCandidate.model_validate(payload)
        if task is ModelTask.AGENT_PLAN_GENERATION:
            return AgentPlanCandidate.model_validate(payload)
        return GroundedResponseDraft.model_validate(payload)

    @staticmethod
    def _failed(
        task: ModelTask,
        status: ModelResultStatus,
        error_code: str,
        message: str,
    ) -> ModelResponse:
        return ModelResponse(
            status=status,
            task=task,
            output=None,
            error_code=error_code,
            message=message,
        )
