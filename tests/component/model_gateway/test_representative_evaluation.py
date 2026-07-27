from pathlib import Path

from customer_service.model_gateway.evaluation import EvaluationCase, load_cases, run_evaluation
from customer_service.model_gateway.fake import FakeModelGateway
from customer_service.model_gateway.schemas import ModelTask

ROOT = Path(__file__).parents[3]
CASES = ROOT / "data" / "evaluation" / "model_gateway" / "cases.v1.json"


def test_representative_t201_to_t203_cases_run_deterministically_with_fake() -> None:
    _, cases = load_cases(CASES)
    fake = FakeModelGateway({case.case_id: _fake_output(case) for case in cases})

    report = run_evaluation(
        fake,
        cases_path=CASES,
        model_identifier="fake-deterministic",
        config_version="test-v1",
    )

    assert report["dataset_version"] == "1.1.0"
    assert report["passed"] == 11
    assert report["total"] == 11
    assert report["code_version"]
    assert report["workspace_state"] in {"clean", "dirty", "unavailable"}
    assert all(case["prompt_version"] for case in report["cases"])
    assert "DEEPSEEK_API_KEY" not in str(report)
    assert "local-test-secret" not in str(report)


def _fake_output(case: EvaluationCase) -> dict[str, object]:
    if case.request.task is ModelTask.GROUNDED_RESPONSE_GENERATION:
        return {
            "text": case.expected["response_text"],
            "evidence_ids": case.expected["evidence_ids"],
        }
    return case.expected
