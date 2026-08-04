import pytest
from pydantic import ValidationError

from customer_service.model_gateway.fake import FakeModelGateway
from customer_service.model_gateway.schemas import (
    EvidenceSnippet,
    ModelRequest,
    ModelTask,
)


def test_fake_is_deterministic_and_never_requires_model_configuration() -> None:
    request = ModelRequest(
        case_id="synthetic-intent",
        task=ModelTask.INTENT_CLASSIFICATION,
        text="我要退货",
        prompt_version="t204-test-v1",
    )
    fake = FakeModelGateway({"synthetic-intent": {"intent": "return_request"}})

    assert fake.generate(request) == fake.generate(request)


def test_gateway_contract_rejects_business_decision_tasks_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ModelRequest.model_validate(
            {
                "case_id": "synthetic",
                "task": "eligibility_decision",
                "text": "合成输入",
                "prompt_version": "t204-test-v1",
                "risk": "low",
            }
        )


def test_grounded_task_requires_real_evidence_in_the_request() -> None:
    with pytest.raises(ValidationError):
        ModelRequest(
            case_id="synthetic-grounded",
            task=ModelTask.GROUNDED_RESPONSE_GENERATION,
            text="请回答",
            prompt_version="t204-test-v1",
        )

    request = ModelRequest(
        case_id="synthetic-grounded",
        task=ModelTask.GROUNDED_RESPONSE_GENERATION,
        text="请回答",
        prompt_version="t204-test-v1",
        evidence=(EvidenceSnippet(evidence_id="POL-1@1", text="合成证据"),),
    )
    assert FakeModelGateway().generate(request).output is not None


def test_fake_agent_plan_is_deterministic_and_rejects_unknown_capability() -> None:
    request = ModelRequest(
        case_id="agent-plan",
        task=ModelTask.AGENT_PLAN_GENERATION,
        text="synthetic",
        prompt_version="t603-v1",
    )
    fake = FakeModelGateway()
    assert fake.generate(request) == fake.generate(request)
    invalid = FakeModelGateway(
        {
            "agent-plan": {
                "schema_version": "agent-plan-v1",
                "intent": "order_query",
                "requested_capability": "order.write",
                "extracted_parameters": {},
                "clarification_fields": [],
                "uncertainty_reason": None,
            }
        }
    ).generate(request)
    assert invalid.status.name == "INVALID_OUTPUT"
