import json
from pathlib import Path
from typing import Any, cast

import pytest

from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.schemas import (
    PolicyAnswerReason,
    PolicyAnswerStatus,
    PolicyQuery,
    RecommendedAction,
)
from customer_service.rag.service import PolicyAnswerService

ROOT = Path(__file__).parents[3]
DATA_ROOT = ROOT / "data"

JsonObject = dict[str, Any]


def load_cases(path: Path) -> list[JsonObject]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return cast(list[JsonObject], document["cases"])


RETRIEVAL_CASES = load_cases(DATA_ROOT / "evaluation" / "retrieval" / "cases.v1.json")
GRAPH_CASES = load_cases(DATA_ROOT / "evaluation" / "graph" / "cases.v1.json")
CASES_BY_ID = {
    str(case["case_id"]): case
    for case in [*RETRIEVAL_CASES, *GRAPH_CASES]
    if "policy_qa" in case["tags"] or case["case_id"] == "AC-FR09-E-001"
}

EXPECTED_RESULTS = {
    "AC-FR03-N-001": (
        PolicyAnswerStatus.ANSWERED,
        RecommendedAction.ANSWER,
        PolicyAnswerReason.CURRENT_POLICY,
    ),
    "AC-FR03-E-001": (
        PolicyAnswerStatus.INSUFFICIENT_EVIDENCE,
        RecommendedAction.CLARIFY,
        PolicyAnswerReason.EXPIRED_ONLY,
    ),
    "AC-FR03-E-002": (
        PolicyAnswerStatus.INSUFFICIENT_EVIDENCE,
        RecommendedAction.CLARIFY,
        PolicyAnswerReason.NO_RESULT,
    ),
    "AC-FR03-E-003": (
        PolicyAnswerStatus.CONFLICT,
        RecommendedAction.ESCALATE,
        PolicyAnswerReason.CONFLICTING_POLICIES,
    ),
    "AC-FR09-E-001": (
        PolicyAnswerStatus.INSUFFICIENT_EVIDENCE,
        RecommendedAction.CLARIFY,
        PolicyAnswerReason.NO_RESULT,
    ),
}


@pytest.fixture(scope="module")
def service() -> PolicyAnswerService:
    return PolicyAnswerService(PolicyCatalog.from_manifest(DATA_ROOT / "manifest.json"))


@pytest.mark.parametrize("case_id", sorted(EXPECTED_RESULTS))
def test_t002_policy_case_contracts(case_id: str, service: PolicyAnswerService) -> None:
    case = CASES_BY_ID[case_id]
    entities = cast(JsonObject, case["user_input"]["required_entities"])
    result = service.answer(
        PolicyQuery(
            category=str(entities["category"]),
            return_reason=(str(entities["return_reason"]) if "return_reason" in entities else None),
        )
    )

    expected_status, expected_action, expected_reason = EXPECTED_RESULTS[case_id]
    assert result.status is expected_status
    assert result.action is expected_action
    assert result.reason is expected_reason

    fixture_policy_ids = set(
        cast(list[str], case["preconditions"]["fixture_refs"].get("policy_ids", []))
    )
    if result.status is PolicyAnswerStatus.ANSWERED:
        assert result.answer is not None
        assert {citation.policy_id for citation in result.citations} == fixture_policy_ids
        public_text = " ".join(
            [result.message, result.answer, *(citation.source for citation in result.citations)]
        )
    else:
        assert result.answer is None
        assert result.citations == ()
        public_text = result.message

    for required_text in case["expected_terminal_state"]["must_include"]:
        assert required_text in public_text
    for forbidden_text in case["expected_terminal_state"]["must_not_include"]:
        assert forbidden_text not in public_text


def test_t002_policy_cases_are_selected_by_semantics_not_exact_utterance() -> None:
    assert set(CASES_BY_ID) == set(EXPECTED_RESULTS)
    for case in CASES_BY_ID.values():
        assert case["user_input"]["acceptance_basis"] == "semantic_match"
        assert len(case["user_input"]["utterance_examples"]) >= 2
