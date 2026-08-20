import json
import subprocess
from pathlib import Path

from customer_service.agent_http.evaluation import report_outcome_is_consistent

ROOT = Path(__file__).parents[2]


def test_t608_implementation_and_release_status_are_consistent() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    releases = (ROOT / "docs/RELEASES.md").read_text(encoding="utf-8")
    tasks = (ROOT / "TASKS.md").read_text(encoding="utf-8")
    report = (ROOT / "docs/task-reports/T-608.md").read_text(encoding="utf-8")
    combined = "\n".join((readme, releases, tasks, report))

    assert "T-601～T-608 与 Docker 发布验证闭环均已通过 Reviewer" in readme
    assert "T-608 已通过 Reviewer" in releases
    assert "Reviewer 最终审查 `PASS`" in tasks
    assert "Reviewer 最终审查 `PASS`" in report
    assert "真实 DeepSeek HTTP" in combined
    assert "4/4 `PASSED`" in combined
    assert "BLOCKED: 3/4" in report
    assert "BLOCKED: 0/4" in report
    assert "当前候选版本为 `1.0.0rc3` / `v1.0.0-rc.3`" in tasks
    assert "实现待开始" not in releases
    assert "本任务尚未实现" not in tasks
    assert "T-608 仅设计审查已通过，尚未实现或验收" not in readme


def test_final_deepseek_report_is_passed_and_does_not_expose_sensitive_data() -> None:
    report = (ROOT / "docs/task-reports/T-608.md").read_text(encoding="utf-8")
    final = json.loads(
        (ROOT / "docs/evaluations/t608-deepseek-http-2026-08-11-final-review.json").read_text(
            encoding="utf-8"
        )
    )
    assert final["status"] == "PASSED" and final["passed"] == final["total"] == 4
    assert final["workspace_digest"] == (
        "ca171d5b816c25b515b2bc3fa940ece10aee94f35e5105961ce7a0ec03fa29f9"
    )
    assert report_outcome_is_consistent(final)
    assert "API Key" not in json.dumps(final)
    assert "4/4 `PASSED`" in report


def test_rc2_tag_is_preserved_while_rc3_is_the_current_candidate() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    releases = (ROOT / "docs/RELEASES.md").read_text(encoding="utf-8")
    tasks = (ROOT / "TASKS.md").read_text(encoding="utf-8")
    report = (ROOT / "docs/task-reports/T-608.md").read_text(encoding="utf-8")
    tags = subprocess.run(
        ["git", "tag", "--list", "v1.0.0-rc.2"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    combined = "\n".join((readme, releases, tasks, report))

    assert "v1.0.0-rc.2" in tags
    assert "Tag 尚未创建" not in combined
    assert "v1.0.0-rc.3" in combined
    assert "v1.0.0-rc.2` 标签保留不移动" in combined
    assert "T-608 已通过 Reviewer `PASS`" in combined
    assert "Docker post-fix 闭环获 Reviewer `PASS`" in combined
