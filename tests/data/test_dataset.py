import json
import re
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

DATA_ROOT = Path(__file__).parents[2] / "data"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@([^@\s]+)$")
FORBIDDEN_IDENTITY_KEYS = {"address", "id_card", "phone", "real_name"}
REQUIRED_SCENARIOS = {
    "normal_return",
    "quality_issue",
    "return_boundary_date",
    "overdue_return",
    "high_value_order",
    "order_not_found",
    "order_unauthorized",
    "active_policy",
    "expired_policy",
    "policy_no_result",
    "conflicting_policies",
}

JsonObject = dict[str, Any]


def load_json(path: Path) -> JsonObject:
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return cast(JsonObject, raw)


MANIFEST = load_json(DATA_ROOT / "manifest.json")
DATA_FILES = [DATA_ROOT / relative_path for relative_path in MANIFEST["files"]]
DOCUMENTS = {path: load_json(path) for path in DATA_FILES}


def records(key: str) -> list[JsonObject]:
    result: list[JsonObject] = []
    for document in DOCUMENTS.values():
        values = document.get(key, [])
        assert isinstance(values, list)
        result.extend(cast(list[JsonObject], values))
    return result


def index_by(values: Iterable[JsonObject], key: str) -> dict[str, JsonObject]:
    indexed = {str(value[key]): value for value in values}
    assert len(indexed) == len(list(values))
    return indexed


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def walk_json(value: Any) -> Iterable[tuple[str | None, Any]]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key), nested
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield None, nested
            yield from walk_json(nested)


def test_manifest_files_exist_and_versions_match() -> None:
    assert MANIFEST["dataset_version"] == "1.0.0"
    assert MANIFEST["reference_date"] == "2026-07-20"
    assert MANIFEST["synthetic_data_only"] is True
    assert len(DATA_FILES) == len(set(DATA_FILES))

    for path, document in DOCUMENTS.items():
        assert path.is_file()
        assert document["dataset_version"] == MANIFEST["dataset_version"]


def test_records_have_unique_ids_and_business_metadata() -> None:
    entity_keys = {
        "users": "user_id",
        "products": "product_id",
        "orders": "order_id",
        "service_cases": "service_case_id",
        "policies": "policy_id",
    }

    for collection, identifier in entity_keys.items():
        values = records(collection)
        assert values
        identifiers = [value[identifier] for value in values]
        assert len(identifiers) == len(set(identifiers))
        for value in values:
            assert isinstance(value["scenario_tags"], list)
            assert value["business_purpose"]
            assert value["expected_behavior"]


def test_order_references_amounts_and_dates_are_consistent() -> None:
    users = index_by(records("users"), "user_id")
    products = index_by(records("products"), "product_id")
    orders = records("orders")
    reference_date = date.fromisoformat(MANIFEST["reference_date"])
    item_ids: set[str] = set()

    for order in orders:
        assert order["user_id"] in users
        assert order["status"] == "delivered"
        placed_at = parse_timestamp(order["placed_at"])
        delivered_at = parse_timestamp(order["delivered_at"])
        assert placed_at <= delivered_at
        assert delivered_at.date() <= reference_date

        total = Decimal("0")
        assert len(order["items"]) == 1
        for item in order["items"]:
            assert item["order_item_id"] not in item_ids
            item_ids.add(item["order_item_id"])
            assert item["product_id"] in products
            assert item["quantity"] > 0
            unit_price = Decimal(item["unit_price"])
            line_total = Decimal(item["line_total"])
            assert unit_price > 0
            assert line_total == unit_price * item["quantity"]
            total += line_total

        assert order["currency"] == "CNY"
        assert total == Decimal(order["total_amount"])


def test_service_case_references_are_consistent() -> None:
    users = index_by(records("users"), "user_id")
    orders = index_by(records("orders"), "order_id")

    for service_case in records("service_cases"):
        order = orders[service_case["order_id"]]
        order_item_ids = {item["order_item_id"] for item in order["items"]}
        assert service_case["user_id"] in users
        assert service_case["user_id"] == order["user_id"]
        assert service_case["order_item_id"] in order_item_ids
        assert service_case["currency"] == order["currency"]
        assert Decimal(service_case["requested_amount"]) <= Decimal(order["total_amount"])
        assert parse_timestamp(service_case["created_at"]) >= parse_timestamp(order["delivered_at"])


def test_required_order_scenarios_have_stable_facts() -> None:
    scenarios = MANIFEST["scenario_references"]
    orders = index_by(records("orders"), "order_id")
    reference_date = date.fromisoformat(MANIFEST["reference_date"])

    normal = orders[scenarios["normal_return"]["order_id"]]
    quality = orders[scenarios["quality_issue"]["order_id"]]
    boundary = orders[scenarios["return_boundary_date"]["order_id"]]
    overdue = orders[scenarios["overdue_return"]["order_id"]]
    high_value = orders[scenarios["high_value_order"]["order_id"]]

    assert (reference_date - parse_timestamp(normal["delivered_at"]).date()).days < 7
    assert quality["synthetic_issue"]["issue_code"]
    assert (reference_date - parse_timestamp(quality["delivered_at"]).date()).days <= 30
    assert (reference_date - parse_timestamp(boundary["delivered_at"]).date()).days == 7
    assert (reference_date - parse_timestamp(overdue["delivered_at"]).date()).days == 8
    assert Decimal(high_value["total_amount"]) == Decimal("9999.00")


def test_order_not_found_and_unauthorized_facts_are_consistent() -> None:
    scenarios = MANIFEST["scenario_references"]
    orders = index_by(records("orders"), "order_id")
    users = index_by(records("users"), "user_id")
    missing = scenarios["order_not_found"]
    unauthorized = scenarios["order_unauthorized"]

    assert missing["user_id"] in users
    assert missing["order_id"] not in orders
    assert unauthorized["requesting_user_id"] in users
    assert unauthorized["owner_user_id"] in users
    assert unauthorized["requesting_user_id"] != unauthorized["owner_user_id"]
    assert orders[unauthorized["order_id"]]["user_id"] == unauthorized["owner_user_id"]


def test_policy_dates_categories_and_required_scenarios_are_consistent() -> None:
    scenarios = MANIFEST["scenario_references"]
    products = index_by(records("products"), "product_id")
    policies = index_by(records("policies"), "policy_id")
    product_categories = {product["category"] for product in products.values()}
    reference_date = date.fromisoformat(MANIFEST["reference_date"])

    for policy in policies.values():
        effective_from = date.fromisoformat(policy["effective_from"])
        effective_to = date.fromisoformat(policy["effective_to"])
        assert effective_from <= effective_to
        assert set(policy["applicable_categories"]) <= product_categories
        assert policy["source"].startswith("synthetic://")

    active = policies[scenarios["active_policy"]["policy_id"]]
    expired = policies[scenarios["expired_policy"]["policy_id"]]
    assert date.fromisoformat(active["effective_from"]) <= reference_date
    assert date.fromisoformat(active["effective_to"]) >= reference_date
    assert active["status"] == "published"
    assert date.fromisoformat(expired["effective_to"]) < reference_date
    assert expired["status"] == "expired"

    no_result_category = scenarios["policy_no_result"]["category"]
    assert products[scenarios["policy_no_result"]["product_id"]]["category"] == no_result_category
    assert all(
        no_result_category not in policy["applicable_categories"] for policy in policies.values()
    )

    conflict = scenarios["conflicting_policies"]
    conflicting = [policies[policy_id] for policy_id in conflict["policy_ids"]]
    assert len(conflicting) == 2
    assert {policy["conflict_group"] for policy in conflicting} == {"CONFLICT-SMART-HOME-001"}
    assert {policy["decision"] for policy in conflicting} == {
        "allow_if_resalable",
        "deny_after_delivery",
    }
    for policy in conflicting:
        assert conflict["category"] in policy["applicable_categories"]
        assert date.fromisoformat(policy["effective_from"]) <= reference_date
        assert date.fromisoformat(policy["effective_to"]) >= reference_date


def test_all_required_scenarios_are_declared_and_tagged() -> None:
    assert set(MANIFEST["scenario_references"]) >= REQUIRED_SCENARIOS
    tags: set[str] = set()
    for collection in ("users", "products", "orders", "service_cases", "policies"):
        for value in records(collection):
            tags.update(value["scenario_tags"])
    assert REQUIRED_SCENARIOS - {"order_not_found"} <= tags


def test_identity_data_is_explicitly_synthetic_and_non_personal() -> None:
    for user in records("users"):
        assert user["is_synthetic"] is True
        match = EMAIL_PATTERN.fullmatch(user["email"])
        assert match is not None
        assert match.group(1) == "example.invalid"

    for document in [MANIFEST, *DOCUMENTS.values()]:
        for key, value in walk_json(document):
            if key is not None:
                assert key.lower() not in FORBIDDEN_IDENTITY_KEYS
            if key == "email":
                assert isinstance(value, str)
                assert value.endswith("@example.invalid")
