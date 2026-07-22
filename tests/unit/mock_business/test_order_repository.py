import json
from pathlib import Path
from typing import Any

import pytest

from mock_business.repository import (
    MockBusinessDataError,
    OrderRepository,
    OrderSourceStatus,
)

ROOT = Path(__file__).parents[3]
DATA_MANIFEST = ROOT / "data" / "manifest.json"


def test_fixed_repository_checks_ownership_at_source_boundary() -> None:
    repository = OrderRepository.from_manifest(DATA_MANIFEST)

    found = repository.lookup(
        current_user_id="USR-DEMO-001",
        order_id="ORD-NORMAL-001",
    )
    unauthorized = repository.lookup(
        current_user_id="USR-DEMO-001",
        order_id="ORD-OTHER-USER-001",
    )
    missing = repository.lookup(
        current_user_id="USR-DEMO-001",
        order_id="ORD-NOT-FOUND-001",
    )

    assert found.status is OrderSourceStatus.FOUND
    assert found.order is not None
    assert unauthorized.status is OrderSourceStatus.UNAUTHORIZED
    assert unauthorized.order is None
    assert missing.status is OrderSourceStatus.NOT_FOUND
    assert missing.order is None


def write_dataset(
    root: Path,
    *,
    order_dataset_version: str = "1.0.0",
    orders: list[dict[str, Any]] | None = None,
    order_owner: str = "USR-DEMO-001",
    order_file: str = "seed/orders/orders.v1.json",
) -> Path:
    manifest = {
        "dataset_name": "test-orders",
        "dataset_version": "1.0.0",
        "reference_date": "2026-07-20",
        "files": ["seed/users/users.v1.json", order_file],
    }
    users = {
        "dataset_version": "1.0.0",
        "users": [{"user_id": "USR-DEMO-001", "role": "consumer"}],
    }
    order = {
        "order_id": "ORD-TEST-001",
        "user_id": order_owner,
        "status": "delivered",
        "placed_at": "2026-07-01T09:00:00Z",
        "delivered_at": "2026-07-02T10:00:00Z",
        "currency": "CNY",
        "total_amount": "10.00",
        "items": [
            {
                "order_item_id": "ITEM-TEST-001",
                "product_id": "PROD-TEST-001",
                "quantity": 1,
                "unit_price": "10.00",
                "line_total": "10.00",
            }
        ],
    }

    manifest_path = root / "manifest.json"
    users_path = root / "seed" / "users" / "users.v1.json"
    orders_path = root / order_file
    users_path.parent.mkdir(parents=True, exist_ok=True)
    orders_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    users_path.write_text(json.dumps(users), encoding="utf-8")
    orders_path.write_text(
        json.dumps(
            {
                "dataset_version": order_dataset_version,
                "orders": orders if orders is not None else [order],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_repository_rejects_order_dataset_version_mismatch(tmp_path: Path) -> None:
    manifest = write_dataset(tmp_path, order_dataset_version="2.0.0")

    with pytest.raises(MockBusinessDataError, match="dataset version"):
        OrderRepository.from_manifest(manifest)


def test_repository_rejects_duplicate_order_ids(tmp_path: Path) -> None:
    manifest = write_dataset(tmp_path)
    order_document = json.loads(
        (tmp_path / "seed" / "orders" / "orders.v1.json").read_text(encoding="utf-8")
    )
    order = order_document["orders"][0]
    manifest = write_dataset(tmp_path, orders=[order, order])

    with pytest.raises(MockBusinessDataError, match="duplicate order_id"):
        OrderRepository.from_manifest(manifest)


def test_repository_rejects_order_with_unknown_owner(tmp_path: Path) -> None:
    manifest = write_dataset(tmp_path, order_owner="USR-UNKNOWN-001")

    with pytest.raises(MockBusinessDataError, match="unknown user"):
        OrderRepository.from_manifest(manifest)


def test_repository_rejects_missing_declared_order_file(tmp_path: Path) -> None:
    manifest = write_dataset(tmp_path, order_file="seed/orders/missing.json")
    (tmp_path / "seed" / "orders" / "missing.json").unlink()

    with pytest.raises(MockBusinessDataError, match="does not exist"):
        OrderRepository.from_manifest(manifest)
