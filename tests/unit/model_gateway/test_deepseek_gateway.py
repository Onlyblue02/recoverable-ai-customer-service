import json

import httpx
from pydantic import SecretStr

from customer_service.infrastructure.config.settings import DeepSeekSettings
from customer_service.model_gateway.deepseek import DeepSeekModelGateway
from customer_service.model_gateway.schemas import (
    EvidenceSnippet,
    ModelRequest,
    ModelResultStatus,
    ModelTask,
)


def request(task: ModelTask = ModelTask.INTENT_CLASSIFICATION) -> ModelRequest:
    evidence: tuple[EvidenceSnippet, ...] = ()
    if task in {
        ModelTask.GROUNDED_RESPONSE_GENERATION,
        ModelTask.AGENT_RESPONSE_DRAFT_GENERATION,
    }:
        evidence = (EvidenceSnippet(evidence_id="POL-1@1", text="合成政策证据"),)
    return ModelRequest(
        case_id="synthetic-case",
        task=task,
        text="合成用户输入",
        prompt_version="t204-test-v1",
        evidence=evidence,
    )


def configured_settings() -> DeepSeekSettings:
    return DeepSeekSettings(
        deepseek_api_key=SecretStr("local-test-secret"),
        deepseek_model="deepseek-test-model",
        deepseek_base_url="https://deepseek.example",
    )


def response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_missing_key_safely_degrades_without_a_network_call() -> None:
    gateway = DeepSeekModelGateway(
        DeepSeekSettings(
            deepseek_api_key=SecretStr(""),
            deepseek_model="deepseek-test-model",
        )
    )

    result = gateway.generate(request())

    assert result.status is ModelResultStatus.UNAVAILABLE
    assert result.error_code == "DEEPSEEK_NOT_CONFIGURED"
    assert result.output is None


def test_valid_structured_response_is_parsed() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: response('{"intent":"return_request"}'))
    )
    result = DeepSeekModelGateway(configured_settings(), client=client).generate(request())

    assert result.status is ModelResultStatus.SUCCEEDED
    assert result.output is not None
    assert result.output.model_dump() == {"intent": "return_request"}


def test_invalid_output_is_repaired_once_then_accepted() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response("not-json" if calls == 1 else '{"intent":"policy_question"}')

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = DeepSeekModelGateway(configured_settings(), client=client).generate(request())

    assert result.status is ModelResultStatus.SUCCEEDED
    assert calls == 2


def test_invalid_output_after_one_repair_safely_degrades() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response('{"intent":"not-an-allowed-intent"}')

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = DeepSeekModelGateway(configured_settings(), client=client).generate(request())

    assert result.status is ModelResultStatus.INVALID_OUTPUT
    assert result.error_code == "DEEPSEEK_INVALID_STRUCTURED_OUTPUT"
    assert result.output is None
    assert calls == 2


def test_grounded_draft_cannot_cite_evidence_outside_this_request() -> None:
    content = json.dumps({"text": "伪造答案", "evidence_ids": ["POL-FAKE@1"]})
    client = httpx.Client(transport=httpx.MockTransport(lambda _: response(content)))
    result = DeepSeekModelGateway(configured_settings(), client=client).generate(
        request(ModelTask.GROUNDED_RESPONSE_GENERATION)
    )

    assert result.status is ModelResultStatus.INVALID_OUTPUT
    assert result.output is None


def test_provider_exception_is_safely_sanitized() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("password=secret host=internal")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = DeepSeekModelGateway(configured_settings(), client=client).generate(request())

    assert result.status is ModelResultStatus.PROVIDER_FAILURE
    assert "password" not in result.model_dump_json()
    assert "internal" not in result.model_dump_json()


def test_agent_plan_is_schema_checked_and_repaired_once() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response(
            "not-json"
            if calls == 1
            else json.dumps(
                {
                    "schema_version": "agent-plan-v1",
                    "intent": "policy_question",
                    "requested_capability": "policy.lookup",
                    "extracted_parameters": {},
                    "clarification_fields": [],
                    "uncertainty_reason": None,
                }
            )
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = DeepSeekModelGateway(configured_settings(), client=client).generate(
        request(ModelTask.AGENT_PLAN_GENERATION)
    )
    assert result.status is ModelResultStatus.SUCCEEDED
    assert calls == 2


def test_agent_plan_invalid_after_repair_safely_degrades() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: response('{"schema_version":"agent-plan-v1","intent":"order_query"}')
        )
    )
    result = DeepSeekModelGateway(configured_settings(), client=client).generate(
        request(ModelTask.AGENT_PLAN_GENERATION)
    )
    assert result.status is ModelResultStatus.INVALID_OUTPUT


def test_agent_response_schema_is_repaired_once_then_accepted() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response(
            "not-json"
            if calls == 1
            else json.dumps(
                {
                    "schema_version": "agent-response-draft-v1",
                    "text": "根据可信证据处理。",
                    "claims": [{"claim_type": "policy", "evidence_ids": ["POL-1@1"]}],
                }
            )
        )

    result = DeepSeekModelGateway(
        configured_settings(), client=httpx.Client(transport=httpx.MockTransport(handler))
    ).generate(request(ModelTask.AGENT_RESPONSE_DRAFT_GENERATION))
    assert result.status is ModelResultStatus.SUCCEEDED
    assert calls == 2


def test_agent_response_invalid_or_unknown_reference_after_repair_is_rejected() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response(
            json.dumps(
                {
                    "schema_version": "agent-response-draft-v1",
                    "text": "伪造",
                    "claims": [{"claim_type": "approval", "evidence_ids": ["EVD-FAKE"]}],
                }
            )
        )

    result = DeepSeekModelGateway(
        configured_settings(), client=httpx.Client(transport=httpx.MockTransport(handler))
    ).generate(request(ModelTask.AGENT_RESPONSE_DRAFT_GENERATION))
    assert result.status is ModelResultStatus.INVALID_OUTPUT
    assert result.output is None and calls == 2
