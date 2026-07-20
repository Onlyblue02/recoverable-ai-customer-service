import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from customer_service.rag.catalog import PolicyCatalog, PolicyCatalogError
from customer_service.rag.schemas import (
    PolicyAnswerReason,
    PolicyAnswerResult,
    PolicyAnswerStatus,
    PolicyDocument,
    PolicyQuery,
    RecommendedAction,
)
from customer_service.rag.service import PolicyAnswerService

ROOT = Path(__file__).parents[3]
DATA_MANIFEST = ROOT / "data" / "manifest.json"


@pytest.fixture
def service() -> PolicyAnswerService:
    return PolicyAnswerService(PolicyCatalog.from_manifest(DATA_MANIFEST))


def test_current_policy_returns_grounded_answer(service: PolicyAnswerService) -> None:
    result = service.answer(
        PolicyQuery(category="general_merchandise", return_reason="changed_mind")
    )

    assert result.status is PolicyAnswerStatus.ANSWERED
    assert result.action is RecommendedAction.ANSWER
    assert result.reason is PolicyAnswerReason.CURRENT_POLICY
    assert result.answer is not None
    assert "七个自然日" in result.answer
    assert result.candidate_policy_ids == ("POL-ACTIVE-STANDARD-001",)
    assert [citation.policy_id for citation in result.citations] == ["POL-ACTIVE-STANDARD-001"]
    assert result.citations[0].source == "synthetic://racs/policies/standard-return/v1"


def test_effective_date_boundary_is_inclusive(service: PolicyAnswerService) -> None:
    result = service.answer(
        PolicyQuery(
            category="general_merchandise",
            return_reason="changed_mind",
            as_of=date(2026, 12, 31),
        )
    )

    assert result.status is PolicyAnswerStatus.ANSWERED


def test_quality_reason_selects_quality_policy(service: PolicyAnswerService) -> None:
    result = service.answer(PolicyQuery(category="electronics", return_reason="quality_issue"))

    assert result.status is PolicyAnswerStatus.ANSWERED
    assert result.candidate_policy_ids == ("POL-ACTIVE-QUALITY-001",)
    assert result.citations[0].source == "synthetic://racs/policies/quality-return/v1"
    assert "三十个自然日" in (result.answer or "")


def test_policy_after_effective_window_is_not_current(service: PolicyAnswerService) -> None:
    result = service.answer(
        PolicyQuery(
            category="general_merchandise",
            return_reason="changed_mind",
            as_of=date(2027, 1, 1),
        )
    )

    assert result.status is PolicyAnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.reason is PolicyAnswerReason.EXPIRED_ONLY
    assert result.answer is None
    assert result.citations == ()


def test_expired_policy_cannot_form_current_answer(service: PolicyAnswerService) -> None:
    result = service.answer(PolicyQuery(category="seasonal_sports", return_reason="changed_mind"))

    assert result.status is PolicyAnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.action is RecommendedAction.CLARIFY
    assert result.reason is PolicyAnswerReason.EXPIRED_ONLY
    assert result.candidate_policy_ids == ("POL-EXPIRED-SEASONAL-001",)
    assert result.answer is None
    assert result.citations == ()


def test_uncovered_category_returns_no_result(service: PolicyAnswerService) -> None:
    result = service.answer(PolicyQuery(category="custom_collectible"))

    assert result.status is PolicyAnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.reason is PolicyAnswerReason.NO_RESULT
    assert result.candidate_policy_ids == ()
    assert result.answer is None
    assert result.citations == ()


def test_conflicting_current_policies_escalate_without_answer(
    service: PolicyAnswerService,
) -> None:
    result = service.answer(PolicyQuery(category="smart_home", return_reason="changed_mind"))

    assert result.status is PolicyAnswerStatus.CONFLICT
    assert result.action is RecommendedAction.ESCALATE
    assert result.reason is PolicyAnswerReason.CONFLICTING_POLICIES
    assert set(result.candidate_policy_ids) == {
        "POL-CONFLICT-SMART-HOME-ALLOW-001",
        "POL-CONFLICT-SMART-HOME-DENY-001",
    }
    assert result.answer is None
    assert result.citations == ()


def test_missing_reason_is_clarified_when_category_has_multiple_policy_reasons(
    service: PolicyAnswerService,
) -> None:
    result = service.answer(PolicyQuery(category="general_merchandise"))

    assert result.status is PolicyAnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.action is RecommendedAction.CLARIFY
    assert result.reason is PolicyAnswerReason.MISSING_RETURN_REASON
    assert result.answer is None


def test_multiple_agreeing_sources_without_priority_are_not_selected_arbitrarily() -> None:
    original = PolicyCatalog.from_manifest(DATA_MANIFEST)
    standard = next(
        policy for policy in original.policies if policy.policy_id == "POL-ACTIVE-STANDARD-001"
    )
    duplicate = PolicyDocument.model_validate(
        {
            **standard.model_dump(),
            "policy_id": "POL-ACTIVE-STANDARD-002",
            "title": "另一份普通退货政策",
            "source": "synthetic://racs/policies/standard-return/v2",
            "content": "普通商品在七日内可按另一份流程申请退货。",
        }
    )
    catalog = PolicyCatalog(
        dataset_name=original.dataset_name,
        dataset_version=original.dataset_version,
        reference_date=original.reference_date,
        policies=(standard, duplicate),
    )

    result = PolicyAnswerService(catalog).answer(
        PolicyQuery(category="general_merchandise", return_reason="changed_mind")
    )

    assert result.status is PolicyAnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.reason is PolicyAnswerReason.AMBIGUOUS_SOURCES
    assert result.answer is None
    assert result.citations == ()


def test_result_schema_rejects_deterministic_answer_without_answered_status() -> None:
    with pytest.raises(ValidationError):
        PolicyAnswerResult(
            status=PolicyAnswerStatus.INSUFFICIENT_EVIDENCE,
            action=RecommendedAction.CLARIFY,
            reason=PolicyAnswerReason.NO_RESULT,
            message="缺少政策依据。",
            answer="该商品可以退货。",
            citations=(),
            candidate_policy_ids=(),
        )


def write_catalog_fixture(
    root: Path,
    *,
    dataset_version: str = "1.0.0",
    policies: list[dict[str, Any]] | None = None,
    manifest_file: str = "knowledge/policies.json",
) -> Path:
    manifest = {
        "dataset_name": "fixture-data",
        "dataset_version": "1.0.0",
        "reference_date": "2026-07-20",
        "files": [manifest_file],
    }
    policy = {
        "policy_id": "POL-TEST-001",
        "policy_version": "1.0.0",
        "title": "测试政策",
        "source": "synthetic://test/policy",
        "status": "published",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "applicable_categories": ["test_category"],
        "return_reason": "changed_mind",
        "decision": "allow_if_resalable",
        "content": "测试政策内容。",
    }
    manifest_path = root / "manifest.json"
    policy_path = root / manifest_file
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    policy_path.write_text(
        json.dumps(
            {
                "dataset_version": dataset_version,
                "policies": policies if policies is not None else [policy],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_catalog_rejects_dataset_version_mismatch(tmp_path: Path) -> None:
    manifest_path = write_catalog_fixture(tmp_path, dataset_version="2.0.0")

    with pytest.raises(PolicyCatalogError, match="dataset version"):
        PolicyCatalog.from_manifest(manifest_path)


def test_catalog_rejects_duplicate_policy_ids(tmp_path: Path) -> None:
    manifest_path = write_catalog_fixture(tmp_path)
    policy_document = json.loads(
        (tmp_path / "knowledge" / "policies.json").read_text(encoding="utf-8")
    )
    duplicate = policy_document["policies"][0]
    manifest_path = write_catalog_fixture(tmp_path, policies=[duplicate, duplicate])

    with pytest.raises(PolicyCatalogError, match="duplicate policy_id"):
        PolicyCatalog.from_manifest(manifest_path)


def test_catalog_rejects_missing_policy_file(tmp_path: Path) -> None:
    manifest_path = write_catalog_fixture(tmp_path, manifest_file="knowledge/missing.json")
    (tmp_path / "knowledge" / "missing.json").unlink()

    with pytest.raises(PolicyCatalogError, match="does not exist"):
        PolicyCatalog.from_manifest(manifest_path)
