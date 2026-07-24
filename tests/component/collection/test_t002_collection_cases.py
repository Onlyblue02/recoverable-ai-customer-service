import json
from pathlib import Path
from typing import Any, cast

import pytest

from customer_service.collection.schemas import (
    CollectionContext,
    CollectionRequest,
)
from customer_service.collection.service import ReturnInformationCollectionService

ROOT = Path(__file__).parents[3]
CASES_PATH = ROOT / "data" / "evaluation" / "routing" / "cases.v1.json"
JsonObject = dict[str, Any]


def load_cases() -> dict[str, JsonObject]:
    document = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return {
        str(case["case_id"]): cast(JsonObject, case)
        for case in document["cases"]
        if "FR-05" in case["requirements"]
    }


CASES = load_cases()


@pytest.mark.parametrize("case_id", ("AC-FR05-N-001", "AC-FR05-E-001"))
def test_t002_collection_case_through_public_service(case_id: str) -> None:
    case = CASES[case_id]
    initial = case["preconditions"]["initial_state"]
    message = str(case["user_input"]["utterance_examples"][0])
    context = CollectionContext(
        order_id=initial.get("confirmed_order_id"),
        return_reason=initial.get("confirmed_return_reason"),
        item_condition=initial.get("confirmed_item_condition"),
    )

    result = ReturnInformationCollectionService().collect(
        CollectionRequest(message=message), context=context
    )

    assert result.stage.value == case["expected_terminal_state"]["status"]
    assert result.business_operation_requested is False
    public_text = result.model_dump_json()
    for required in case["expected_terminal_state"]["must_include"]:
        assert str(required) in public_text
    for forbidden in case["expected_terminal_state"]["must_not_include"]:
        assert str(forbidden) not in public_text


def test_t002_collection_cases_are_selected_by_requirement_and_semantics() -> None:
    assert set(CASES) == {"AC-FR05-N-001", "AC-FR05-E-001"}
    for case in CASES.values():
        assert case["user_input"]["acceptance_basis"] == "semantic_match"
