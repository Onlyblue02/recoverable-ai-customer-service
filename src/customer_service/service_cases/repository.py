import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol


@dataclass(frozen=True)
class StoredServiceCase:
    service_case_id: str
    user_id: str
    order_id: str
    order_item_id: str
    status: str
    idempotency_key: str


@dataclass(frozen=True)
class ServiceCaseDraft:
    user_id: str
    order_id: str
    order_item_id: str
    idempotency_key: str


class ServiceCaseRepository(Protocol):
    def find_by_idempotency_key(self, key: str) -> StoredServiceCase | None: ...

    def create(self, *, draft: ServiceCaseDraft) -> StoredServiceCase | None: ...


class InMemoryServiceCaseRepository:
    """Process-local repository used only for deterministic simulated records."""

    def __init__(self, seed_cases: tuple[StoredServiceCase, ...] = ()) -> None:
        self._by_key = {case.idempotency_key: case for case in seed_cases}
        self._lock = Lock()
        self._next_sequence = 1

    @classmethod
    def from_manifest(cls, manifest_path: Path) -> "InMemoryServiceCaseRepository":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        relative_path = next(
            path for path in manifest["files"] if str(path).startswith("seed/service_cases/")
        )
        document = json.loads((manifest_path.parent / relative_path).read_text(encoding="utf-8"))
        seed_cases = tuple(
            StoredServiceCase(
                service_case_id=str(record["service_case_id"]),
                user_id=str(record["user_id"]),
                order_id=str(record["order_id"]),
                order_item_id=str(record["order_item_id"]),
                status=str(record["status"]),
                idempotency_key=(
                    f"{str(record['user_id']).strip().upper()}|"
                    f"{str(record['order_id']).strip().upper()}|"
                    f"{str(record['order_item_id']).strip().upper()}"
                ),
            )
            for record in document["service_cases"]
        )
        return cls(seed_cases=seed_cases)

    @property
    def case_count(self) -> int:
        return len(self._by_key)

    def find_by_idempotency_key(self, key: str) -> StoredServiceCase | None:
        return self._by_key.get(key)

    def create(self, *, draft: ServiceCaseDraft) -> StoredServiceCase | None:
        with self._lock:
            existing = self._by_key.get(draft.idempotency_key)
            if existing is not None:
                return existing
            case = StoredServiceCase(
                service_case_id=f"SC-SIM-{self._next_sequence:03d}",
                user_id=draft.user_id,
                order_id=draft.order_id,
                order_item_id=draft.order_item_id,
                status="created",
                idempotency_key=draft.idempotency_key,
            )
            self._next_sequence += 1
            self._by_key[case.idempotency_key] = case
            return case
