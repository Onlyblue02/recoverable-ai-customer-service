import json
import re
from collections import defaultdict
from collections.abc import Iterable
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

ROOT = Path(__file__).parents[2]
DATA_ROOT = ROOT / "data"
EVALUATION_ROOT = DATA_ROOT / "evaluation"

JsonObject = dict[str, Any]


def load_json(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(JsonObject, value)


MANIFEST = load_json(EVALUATION_ROOT / "manifest.json")
DATASET_MANIFEST = load_json(DATA_ROOT / "manifest.json")
SCHEMA = load_json(EVALUATION_ROOT / str(MANIFEST["schema"]))
CASE_PATHS = [EVALUATION_ROOT / str(path) for path in MANIFEST["case_files"]]
CASE_DOCUMENTS = [load_json(path) for path in CASE_PATHS]
CASES = cast(
    list[JsonObject],
    [case for document in CASE_DOCUMENTS for case in cast(list[JsonObject], document["cases"])],
)


def dataset_records(key: str) -> list[JsonObject]:
    result: list[JsonObject] = []
    for relative_path in cast(list[str], DATASET_MANIFEST["files"]):
        document = load_json(DATA_ROOT / relative_path)
        result.extend(cast(list[JsonObject], document.get(key, [])))
    return result


def ids_for(collection: str, identifier: str) -> set[str]:
    return {str(record[identifier]) for record in dataset_records(collection)}


def walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_keys(nested)


def cases_with_tag(tag: str) -> list[JsonObject]:
    return [case for case in CASES if tag in cast(list[str], case["tags"])]


def ambiguous_case_variants() -> list[JsonObject]:
    base = deepcopy(CASE_DOCUMENTS[0])
    variants: list[JsonObject] = []

    mutations: list[tuple[tuple[str, ...], Any]] = [
        (("preconditions", "initial_state"), {}),
        (("user_input", "required_entities"), {}),
        (("user_input", "semantic_intent"), ""),
        (("user_input", "semantic_intent"), "x"),
        (("user_input", "semantic_intent"), "   "),
        (("expected_process", "0", "event"), "x"),
        (("expected_process", "0", "assertions", "0"), ""),
        (("expected_process", "0", "assertions", "0"), "x"),
        (("expected_terminal_state", "public_outcome"), "x"),
    ]
    for path, replacement in mutations:
        document = deepcopy(base)
        target: Any = document["cases"][0]
        for component in path[:-1]:
            target = target[int(component)] if component.isdigit() else target[component]
        final = path[-1]
        if final.isdigit():
            target[int(final)] = replacement
        else:
            target[final] = replacement
        variants.append(document)

    missing_field = deepcopy(base)
    del missing_field["cases"][0]["user_input"]["semantic_intent"]
    variants.append(missing_field)
    return variants


def requirement_mapping_errors(cases: list[JsonObject]) -> list[str]:
    errors: list[str] = []
    for case in cases:
        case_id = str(case["case_id"])
        match = re.match(r"^AC-FR(0[1-9]|1[0-2])-", case_id)
        expected = f"FR-{match.group(1)}" if match is not None else None
        if expected is not None and expected not in cast(list[str], case["requirements"]):
            errors.append(f"{case_id} does not include {expected} in requirements")
    return errors


def policy_relationship_errors(cases: list[JsonObject]) -> list[str]:
    errors: list[str] = []
    scenarios = cast(JsonObject, DATASET_MANIFEST["scenario_references"])
    policies = {str(value["policy_id"]): value for value in dataset_records("policies")}
    products = {str(value["product_id"]): value for value in dataset_records("products")}
    reference_date = date.fromisoformat(str(DATASET_MANIFEST["reference_date"]))

    def fixtures(case: JsonObject, key: str) -> set[str]:
        refs = cast(JsonObject, case["preconditions"]["fixture_refs"])
        return set(cast(list[str], refs.get(key, [])))

    def category_for(case: JsonObject) -> str | None:
        entities = cast(JsonObject, case["user_input"]["required_entities"])
        category = entities.get("category")
        return str(category) if category is not None else None

    def policy_is_current(policy: JsonObject) -> bool:
        return (
            policy["status"] == "published"
            and date.fromisoformat(str(policy["effective_from"])) <= reference_date
            and date.fromisoformat(str(policy["effective_to"])) >= reference_date
        )

    for case in cases:
        case_id = str(case["case_id"])
        tags = set(cast(list[str], case["tags"]))
        policy_ids = fixtures(case, "policy_ids")
        product_ids = fixtures(case, "product_ids")
        category = category_for(case)

        if "active_policy" in tags:
            expected = str(scenarios["active_policy"]["policy_id"])
            if policy_ids != {expected}:
                errors.append(f"{case_id} must reference active policy {expected}")
                continue
            policy = policies[expected]
            if not policy_is_current(policy):
                errors.append(f"{case_id} active policy is not current and published")
            if category not in cast(list[str], policy["applicable_categories"]):
                errors.append(f"{case_id} category is outside active policy scope")

        if "expired_policy" in tags:
            expected = str(scenarios["expired_policy"]["policy_id"])
            if policy_ids != {expected}:
                errors.append(f"{case_id} must reference expired policy {expected}")
                continue
            policy = policies[expected]
            if (
                policy["status"] != "expired"
                or date.fromisoformat(str(policy["effective_to"])) >= reference_date
            ):
                errors.append(f"{case_id} policy is not expired at the reference date")
            if category not in cast(list[str], policy["applicable_categories"]):
                errors.append(f"{case_id} category is outside expired policy scope")

        if "no_result" in tags:
            scenario = cast(JsonObject, scenarios["policy_no_result"])
            expected_product = str(scenario["product_id"])
            expected_category = str(scenario["category"])
            if product_ids != {expected_product} or category != expected_category:
                errors.append(f"{case_id} does not match the no-result product and category")
                continue
            if products[expected_product]["category"] != expected_category:
                errors.append(f"{case_id} no-result product category is inconsistent")
            if any(
                expected_category in cast(list[str], policy["applicable_categories"])
                for policy in policies.values()
            ):
                errors.append(f"{case_id} no-result category is covered by a policy")

        if "policy_conflict" in tags:
            scenario = cast(JsonObject, scenarios["conflicting_policies"])
            expected_policies = set(cast(list[str], scenario["policy_ids"]))
            expected_product = str(scenario["product_id"])
            expected_category = str(scenario["category"])
            if (
                policy_ids != expected_policies
                or product_ids != {expected_product}
                or category != expected_category
            ):
                errors.append(f"{case_id} does not reference the complete conflict scenario")
                continue
            selected = [policies[policy_id] for policy_id in expected_policies]
            if products[expected_product]["category"] != expected_category:
                errors.append(f"{case_id} conflict product category is inconsistent")
            if not all(policy_is_current(policy) for policy in selected):
                errors.append(f"{case_id} conflict policies are not simultaneously current")
            conflict_groups = {policy.get("conflict_group") for policy in selected}
            if len(conflict_groups) != 1 or None in conflict_groups:
                errors.append(f"{case_id} conflict policies do not share the expected group")
            if len({policy["decision"] for policy in selected}) != 2:
                errors.append(f"{case_id} conflict policies do not have opposing decisions")
            if not all(
                expected_category in cast(list[str], policy["applicable_categories"])
                for policy in selected
            ):
                errors.append(f"{case_id} conflict category is outside policy scope")
    return errors


def test_schema_is_valid_and_every_module_conforms() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    validator = Draft202012Validator(SCHEMA)

    assert len(CASE_PATHS) == len(set(CASE_PATHS))
    for path, document in zip(CASE_PATHS, CASE_DOCUMENTS, strict=True):
        assert path.is_file()
        errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
        assert not errors, "\n".join(error.message for error in errors)
        assert document["evaluation_version"] == MANIFEST["evaluation_version"]
        assert document["dataset_version"] == DATASET_MANIFEST["dataset_version"]
        assert document["reference_date"] == DATASET_MANIFEST["reference_date"]


@pytest.mark.parametrize("invalid_document", ambiguous_case_variants())
def test_schema_rejects_ambiguous_contracts(invalid_document: JsonObject) -> None:
    assert list(Draft202012Validator(SCHEMA).iter_errors(invalid_document))


def test_case_id_requirement_mapping_rejects_mismatch() -> None:
    invalid_case = deepcopy(CASES[0])
    invalid_case["case_id"] = "AC-FR12-N-999"
    invalid_case["requirements"] = ["FR-01"]
    assert requirement_mapping_errors([invalid_case])


def test_all_case_ids_match_their_declared_requirements() -> None:
    assert not requirement_mapping_errors(CASES)


def test_case_and_terminal_ids_are_globally_unique() -> None:
    case_ids = [str(case["case_id"]) for case in CASES]
    terminal_ids = [str(case["expected_terminal_state"]["terminal_state_id"]) for case in CASES]
    assert len(case_ids) == len(set(case_ids))
    assert len(terminal_ids) == len(set(terminal_ids))


def test_every_p0_requirement_has_normal_and_exception_or_boundary() -> None:
    coverage: defaultdict[str, set[str]] = defaultdict(set)
    for case in CASES:
        for requirement in cast(list[str], case["requirements"]):
            coverage[requirement].add(str(case["polarity"]))

    for requirement in cast(list[str], MANIFEST["coverage_requirements"]):
        assert "normal" in coverage[requirement], requirement
        assert coverage[requirement] & {"exception", "boundary"}, requirement


def test_required_themes_and_exact_e2e_stories_are_present() -> None:
    all_tags = {tag for case in CASES for tag in cast(list[str], case["tags"])}
    assert set(MANIFEST["required_themes"]) <= all_tags

    e2e_cases = [case for case in CASES if case["case_kind"] == "e2e"]
    assert {case["case_id"] for case in e2e_cases} == set(MANIFEST["required_e2e_stories"])
    assert {case["case_id"] for case in e2e_cases} == {
        "E2E-STANDARD-001",
        "E2E-HIGH-RISK-001",
    }


def test_inputs_are_semantic_and_processes_have_an_explicit_order() -> None:
    for case in CASES:
        user_input = cast(JsonObject, case["user_input"])
        examples = cast(list[str], user_input["utterance_examples"])
        assert user_input["acceptance_basis"] == "semantic_match"
        assert len(examples) >= 2
        assert len(examples) == len(set(examples))

        process = cast(list[JsonObject], case["expected_process"])
        assert [step["sequence"] for step in process] == list(range(1, len(process) + 1))


def test_fixture_references_resolve_to_t001_data() -> None:
    available = {
        "user_ids": ids_for("users", "user_id"),
        "order_ids": ids_for("orders", "order_id"),
        "product_ids": ids_for("products", "product_id"),
        "policy_ids": ids_for("policies", "policy_id"),
        "service_case_ids": ids_for("service_cases", "service_case_id"),
    }
    missing_order = str(DATASET_MANIFEST["scenario_references"]["order_not_found"]["order_id"])

    for case in CASES:
        fixture_refs = cast(JsonObject, case["preconditions"]["fixture_refs"])
        for reference_type, references in fixture_refs.items():
            reference_values = cast(list[str], references)
            if reference_type == "order_ids" and "order_not_found" in case["tags"]:
                assert set(reference_values) <= available[reference_type] | {missing_order}
            else:
                assert set(reference_values) <= available[reference_type]


def test_security_and_policy_scenarios_match_t001_facts() -> None:
    scenarios = cast(JsonObject, DATASET_MANIFEST["scenario_references"])
    unauthorized = cast(JsonObject, scenarios["order_unauthorized"])
    unauthorized_cases = cases_with_tag("order_unauthorized")
    assert unauthorized_cases
    for case in unauthorized_cases:
        initial_state = cast(JsonObject, case["preconditions"]["initial_state"])
        assert initial_state["requesting_user_id"] == unauthorized["requesting_user_id"]
        assert unauthorized["order_id"] in case["preconditions"]["fixture_refs"]["order_ids"]

    assert not policy_relationship_errors(CASES)


@pytest.mark.parametrize(
    ("case_id", "fixture_key", "replacement"),
    [
        ("AC-FR03-N-001", "policy_ids", ["POL-EXPIRED-SEASONAL-001"]),
        ("AC-FR03-E-001", "policy_ids", ["POL-ACTIVE-STANDARD-001"]),
        ("AC-FR03-E-002", "product_ids", ["PROD-GENERAL-001"]),
        (
            "AC-FR03-E-003",
            "policy_ids",
            ["POL-CONFLICT-SMART-HOME-ALLOW-001"],
        ),
    ],
)
def test_policy_relationship_gate_rejects_mutated_fixtures(
    case_id: str, fixture_key: str, replacement: list[str]
) -> None:
    case = deepcopy(next(case for case in CASES if case["case_id"] == case_id))
    case["preconditions"]["fixture_refs"][fixture_key] = replacement
    assert policy_relationship_errors([case])


def test_expectations_do_not_contain_execution_results() -> None:
    forbidden_result_keys = {"actual_result", "passed", "failure_reason", "executed_at"}
    for document in CASE_DOCUMENTS:
        assert forbidden_result_keys.isdisjoint(walk_keys(document))


def test_e2e_side_effects_and_resume_contract_are_fixed() -> None:
    by_id = {str(case["case_id"]): case for case in CASES}
    standard = by_id["E2E-STANDARD-001"]
    high_risk = by_id["E2E-HIGH-RISK-001"]

    assert standard["expected_terminal_state"]["business_effects"] == {
        "service_cases_created": 1,
        "approval_tasks_created": 0,
    }
    assert high_risk["expected_terminal_state"]["business_effects"] == {
        "service_cases_created": 1,
        "approval_tasks_created": 1,
    }
    high_risk_events = {step["event"] for step in high_risk["expected_process"]}
    required_events = {
        "persist_interrupt_state",
        "restore_after_interruption",
        "commit_human_approval",
    }
    assert required_events <= high_risk_events
