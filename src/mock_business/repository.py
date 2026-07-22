import json
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Self, cast

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from mock_business.schemas import StoredOrder, StoredUser


class MockBusinessDataError(ValueError):
    """Raised when fixed users and orders cannot form a trusted data boundary."""


JsonObject = dict[str, Any]


def _load_json_object(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MockBusinessDataError(
            f"cannot load mock business data file {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise MockBusinessDataError(f"mock business data file {path} must contain an object")
    return cast(JsonObject, value)


class OrderSourceStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"


class OrderSourceResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: OrderSourceStatus
    order: StoredOrder | None = None

    @model_validator(mode="after")
    def validate_result_contract(self) -> Self:
        if self.status is OrderSourceStatus.FOUND:
            if self.order is None:
                raise ValueError("found source result requires an order")
        elif self.order is not None:
            raise ValueError("failed source result cannot contain an order")
        return self


class OrderRepository:
    def __init__(
        self,
        *,
        dataset_name: str,
        dataset_version: str,
        users: tuple[StoredUser, ...],
        orders: tuple[StoredOrder, ...],
    ) -> None:
        self.dataset_name = dataset_name
        self.dataset_version = dataset_version
        self._user_ids = frozenset(user.user_id for user in users)
        self._orders = {order.order_id: order for order in orders}

    @classmethod
    def from_manifest(cls, manifest_path: Path) -> "OrderRepository":
        manifest = _load_json_object(manifest_path)
        try:
            dataset_name = str(manifest["dataset_name"])
            dataset_version = str(manifest["dataset_version"])
            file_names = cast(list[str], manifest["files"])
        except (KeyError, TypeError, ValueError) as error:
            raise MockBusinessDataError("dataset manifest has invalid order metadata") from error

        data_root = manifest_path.parent.resolve()
        users_path = cls._declared_file(
            data_root,
            file_names,
            prefix=("seed", "users"),
            label="user",
        )
        orders_path = cls._declared_file(
            data_root,
            file_names,
            prefix=("seed", "orders"),
            label="order",
        )
        users_document = _load_json_object(users_path)
        orders_document = _load_json_object(orders_path)
        if users_document.get("dataset_version") != dataset_version:
            raise MockBusinessDataError("dataset version mismatch in user data file")
        if orders_document.get("dataset_version") != dataset_version:
            raise MockBusinessDataError("dataset version mismatch in order data file")

        users = cls._validate_records(
            users_document.get("users"),
            model=StoredUser,
            file_path=users_path,
            collection_name="users",
        )
        orders = cls._validate_records(
            orders_document.get("orders"),
            model=StoredOrder,
            file_path=orders_path,
            collection_name="orders",
        )

        cls._validate_unique_ids((user.user_id for user in users), label="user_id")
        cls._validate_unique_ids((order.order_id for order in orders), label="order_id")
        cls._validate_unique_ids(
            (item.order_item_id for order in orders for item in order.items),
            label="order_item_id",
        )
        user_ids = {user.user_id for user in users}
        for order in orders:
            if order.user_id not in user_ids:
                raise MockBusinessDataError(
                    f"order {order.order_id} references unknown user {order.user_id}"
                )

        return cls(
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            users=users,
            orders=orders,
        )

    @staticmethod
    def _declared_file(
        data_root: Path,
        file_names: list[str],
        *,
        prefix: tuple[str, str],
        label: str,
    ) -> Path:
        matches: list[Path] = []
        for file_name in file_names:
            relative_path = PurePosixPath(file_name)
            if relative_path.parts[:2] != prefix:
                continue
            path = data_root.joinpath(*relative_path.parts).resolve()
            if not path.is_relative_to(data_root):
                raise MockBusinessDataError(f"{label} data path escapes data root")
            if not path.is_file():
                raise MockBusinessDataError(f"{label} data file does not exist: {path}")
            matches.append(path)
        if len(matches) != 1:
            raise MockBusinessDataError(
                f"dataset manifest must declare exactly one {label} data file"
            )
        return matches[0]

    @staticmethod
    def _validate_records[Record: BaseModel](
        raw_records: object,
        *,
        model: type[Record],
        file_path: Path,
        collection_name: str,
    ) -> tuple[Record, ...]:
        if not isinstance(raw_records, list):
            raise MockBusinessDataError(
                f"mock business data file {file_path} must contain {collection_name}"
            )
        try:
            records = tuple(model.model_validate(record) for record in raw_records)
        except ValidationError as error:
            raise MockBusinessDataError(
                f"invalid {collection_name} in {file_path}: {error}"
            ) from error
        if not records:
            raise MockBusinessDataError(f"{collection_name} must not be empty")
        return records

    @staticmethod
    def _validate_unique_ids(values: Any, *, label: str) -> None:
        seen: set[str] = set()
        for value in values:
            if value in seen:
                raise MockBusinessDataError(f"duplicate {label}: {value}")
            seen.add(value)

    def lookup(self, *, current_user_id: str, order_id: str) -> OrderSourceResult:
        order = self._orders.get(order_id)
        if order is None:
            return OrderSourceResult(status=OrderSourceStatus.NOT_FOUND)
        if current_user_id not in self._user_ids or order.user_id != current_user_id:
            return OrderSourceResult(status=OrderSourceStatus.UNAUTHORIZED)
        return OrderSourceResult(status=OrderSourceStatus.FOUND, order=order)
