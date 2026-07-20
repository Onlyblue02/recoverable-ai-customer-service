from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from customer_service.rag.catalog import PolicyCatalog
from customer_service.rag.schemas import (
    PolicyAnswerReason,
    PolicyAnswerResult,
    PolicyAnswerStatus,
    PolicyCitation,
    PolicyDocument,
    PolicyQuery,
    RecommendedAction,
)
from customer_service.rag.service import PolicyAnswerService

ROOT = Path(__file__).parents[3]
DATA_MANIFEST = ROOT / "data" / "manifest.json"
STANDARD_QUERY = PolicyQuery(category="general_merchandise", return_reason="changed_mind")


@pytest.fixture(scope="module")
def catalog() -> PolicyCatalog:
    return PolicyCatalog.from_manifest(DATA_MANIFEST)


def policy_by_id(catalog: PolicyCatalog, policy_id: str) -> PolicyDocument:
    return next(policy for policy in catalog.policies if policy.policy_id == policy_id)


def citation_for(
    policy: PolicyDocument,
    **overrides: object,
) -> PolicyCitation:
    fields: dict[str, object] = {
        "policy_id": policy.policy_id,
        "evidence_id": policy.evidence_id,
        "policy_version": policy.policy_version,
        "title": policy.title,
        "source": policy.source,
        "effective_from": policy.effective_from,
        "effective_to": policy.effective_to,
        "excerpt": policy.content,
    }
    fields.update(overrides)
    return PolicyCitation.model_validate(fields)


def answered_result(
    citation: PolicyCitation,
    *,
    answer: str = "伪造的确定性政策答案。",
) -> PolicyAnswerResult:
    return PolicyAnswerResult(
        status=PolicyAnswerStatus.ANSWERED,
        action=RecommendedAction.ANSWER,
        reason=PolicyAnswerReason.CURRENT_POLICY,
        message=answer,
        answer=answer,
        citations=(citation,),
        candidate_policy_ids=(citation.policy_id,),
    )


def service_with_result(
    catalog: PolicyCatalog,
    result_factory: Callable[[PolicyDocument], PolicyAnswerResult],
) -> PolicyAnswerService:
    return PolicyAnswerService(catalog, answer_assembler=result_factory)


def assert_safe_ungrounded(result: PolicyAnswerResult) -> None:
    assert result.status is PolicyAnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.action is RecommendedAction.CLARIFY
    assert result.reason is PolicyAnswerReason.UNGROUNDED_CITATION
    assert result.answer is None
    assert result.citations == ()


def test_self_consistent_fake_ids_and_source_are_blocked_on_public_path(
    catalog: PolicyCatalog,
) -> None:
    fake_citation = PolicyCitation(
        policy_id="POL-FAKE-999",
        evidence_id="policy:POL-FAKE-999:9.9.9",
        policy_version="9.9.9",
        title="伪造政策",
        source="fake://source",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        excerpt="伪造政策内容。",
    )
    service = service_with_result(catalog, lambda _: answered_result(fake_citation))

    result = service.answer(STANDARD_QUERY)

    assert_safe_ungrounded(result)
    public_result = result.model_dump_json()
    assert "POL-FAKE-999" not in public_result
    assert "fake://source" not in public_result


def test_real_policy_id_with_fake_source_is_blocked_on_public_path(
    catalog: PolicyCatalog,
) -> None:
    standard = policy_by_id(catalog, "POL-ACTIVE-STANDARD-001")
    forged = answered_result(citation_for(standard, source="fake://source"))
    service = service_with_result(catalog, lambda _: forged)

    result = service.answer(STANDARD_QUERY)

    assert_safe_ungrounded(result)
    assert "fake://source" not in result.model_dump_json()


@pytest.mark.parametrize(
    "citation_overrides",
    [
        {"policy_version": "9.9.9"},
        {"evidence_id": "policy:POL-ACTIVE-STANDARD-001:wrong-evidence"},
    ],
    ids=["wrong-version", "wrong-evidence-id"],
)
def test_real_source_with_wrong_version_or_evidence_id_is_blocked_on_public_path(
    catalog: PolicyCatalog,
    citation_overrides: dict[str, object],
) -> None:
    standard = policy_by_id(catalog, "POL-ACTIVE-STANDARD-001")
    forged = answered_result(citation_for(standard, **citation_overrides))
    service = service_with_result(catalog, lambda _: forged)

    result = service.answer(STANDARD_QUERY)

    assert_safe_ungrounded(result)


def test_policy_outside_this_retrieval_result_is_blocked_on_public_path(
    catalog: PolicyCatalog,
) -> None:
    quality = policy_by_id(catalog, "POL-ACTIVE-QUALITY-001")
    forged = answered_result(citation_for(quality))
    service = service_with_result(catalog, lambda _: forged)

    result = service.answer(STANDARD_QUERY)

    assert_safe_ungrounded(result)
    assert result.candidate_policy_ids == ("POL-ACTIVE-STANDARD-001",)


def test_real_retrieved_citation_still_returns_answered(catalog: PolicyCatalog) -> None:
    standard = policy_by_id(catalog, "POL-ACTIVE-STANDARD-001")
    answer = f"根据《{standard.title}》（{standard.policy_id}），{standard.content}"
    grounded = answered_result(citation_for(standard), answer=answer)
    service = service_with_result(catalog, lambda _: grounded)

    result = service.answer(STANDARD_QUERY)

    assert result.status is PolicyAnswerStatus.ANSWERED
    assert result.reason is PolicyAnswerReason.CURRENT_POLICY
    assert result.candidate_policy_ids == (standard.policy_id,)
    assert result.citations == (citation_for(standard),)
