import json
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, cast

from pydantic import ValidationError

from customer_service.rag.schemas import PolicyDocument


class PolicyCatalogError(ValueError):
    """Raised when the fixed policy dataset cannot form a valid catalog."""


JsonObject = dict[str, Any]


def _load_json_object(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyCatalogError(f"cannot load policy data file {path}: {error}") from error
    if not isinstance(value, dict):
        raise PolicyCatalogError(f"policy data file {path} must contain a JSON object")
    return cast(JsonObject, value)


class PolicyCatalog:
    def __init__(
        self,
        *,
        dataset_name: str,
        dataset_version: str,
        reference_date: date,
        policies: tuple[PolicyDocument, ...],
    ) -> None:
        self.dataset_name = dataset_name
        self.dataset_version = dataset_version
        self.reference_date = reference_date
        self.policies = policies

    @classmethod
    def from_manifest(cls, manifest_path: Path) -> "PolicyCatalog":
        manifest = _load_json_object(manifest_path)
        try:
            dataset_name = str(manifest["dataset_name"])
            dataset_version = str(manifest["dataset_version"])
            reference_date = date.fromisoformat(str(manifest["reference_date"]))
            file_names = cast(list[str], manifest["files"])
        except (KeyError, TypeError, ValueError) as error:
            raise PolicyCatalogError("dataset manifest has invalid policy metadata") from error

        data_root = manifest_path.parent.resolve()
        policy_files: list[Path] = []
        for file_name in file_names:
            relative_path = PurePosixPath(file_name)
            if not relative_path.parts or relative_path.parts[0] != "knowledge":
                continue
            path = data_root.joinpath(*relative_path.parts).resolve()
            if not path.is_relative_to(data_root):
                raise PolicyCatalogError(f"policy data path escapes data root: {file_name}")
            if not path.is_file():
                raise PolicyCatalogError(f"policy data file does not exist: {path}")
            policy_files.append(path)

        if not policy_files:
            raise PolicyCatalogError("dataset manifest does not declare policy data files")

        policies: list[PolicyDocument] = []
        seen_ids: set[str] = set()
        for path in policy_files:
            document = _load_json_object(path)
            if document.get("dataset_version") != dataset_version:
                raise PolicyCatalogError(f"dataset version mismatch in policy data file {path}")
            raw_policies = document.get("policies")
            if not isinstance(raw_policies, list):
                raise PolicyCatalogError(f"policy data file {path} must contain policies")
            for raw_policy in raw_policies:
                try:
                    policy = PolicyDocument.model_validate(raw_policy)
                except ValidationError as error:
                    raise PolicyCatalogError(f"invalid policy in {path}: {error}") from error
                if policy.policy_id in seen_ids:
                    raise PolicyCatalogError(f"duplicate policy_id: {policy.policy_id}")
                seen_ids.add(policy.policy_id)
                policies.append(policy)

        if not policies:
            raise PolicyCatalogError("policy catalog must contain at least one policy")
        return cls(
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            reference_date=reference_date,
            policies=tuple(policies),
        )

    def for_category(self, category: str) -> tuple[PolicyDocument, ...]:
        return tuple(policy for policy in self.policies if category in policy.applicable_categories)

    def matching(self, *, category: str, return_reason: str) -> tuple[PolicyDocument, ...]:
        return tuple(
            policy
            for policy in self.for_category(category)
            if policy.return_reason == return_reason
        )
