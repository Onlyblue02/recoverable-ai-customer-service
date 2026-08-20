import tomllib
from pathlib import Path

from customer_service.main import create_app as create_customer_service_app
from mock_business.main import create_app as create_mock_business_app

ROOT = Path(__file__).parents[2]


def _project_version() -> str:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(document["project"]["version"])


def test_public_api_versions_match_the_single_project_version() -> None:
    project_version = _project_version()

    assert create_customer_service_app().version == project_version
    assert create_mock_business_app().version == project_version


def test_v1_local_release_is_recorded_without_remote_publication() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    releases = (ROOT / "docs" / "RELEASES.md").read_text(encoding="utf-8")
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    tasks = (ROOT / "TASKS.md").read_text(encoding="utf-8")

    combined = "\n".join((readme, releases, changelog, tasks))
    assert "## [1.0.0]" in changelog
    assert "当前正式版本为 `1.0.0`" in combined
    assert "未推送远程" in combined
    assert "v1.0.0-rc.4" in releases
    assert "Docker 发布验证记录" in releases


def test_t404_reviewer_pass_does_not_claim_v1_release() -> None:
    tasks = (ROOT / "TASKS.md").read_text(encoding="utf-8")
    report = (ROOT / "docs" / "task-reports" / "T-404.md").read_text(encoding="utf-8")
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    t404_section = tasks.split("### T-404 项目演示与交付材料", maxsplit=1)[1].split(
        "## 9. 后续扩展任务", maxsplit=1
    )[0]

    assert "[x]" in t404_section
    assert "独立 Reviewer 审查 PASS" in t404_section
    assert "最终结论：PASS；允许创建 T-404 普通任务提交，当前不发布 `v1.0.0`" in report
    assert "T-404 已完成独立 Reviewer 审查 PASS" in changelog
    assert "## [1.0.0]" in changelog


def test_release_checks_require_actual_lock_and_compose_evidence() -> None:
    releases = (ROOT / "docs" / "RELEASES.md").read_text(encoding="utf-8")

    assert "uv lock --check" in releases
    assert "docker compose -f deploy/compose.yaml config --quiet" in releases
    assert "实际日志" in releases
