from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_v1_release_validation_records_actual_environment_blockers() -> None:
    report = (ROOT / "docs" / "release-validation-v1.0.0-2026-07-28.md").read_text(encoding="utf-8")
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "uv lock --check" in report
    assert "Updated recoverable-ai-customer-service v0.2.0 -> v0.5.0" in report
    assert "x-docker-expose-session-sharedkey" in report
    assert "registry-1.docker.io/v2/docker/dockerfile/manifests/1" in report
    assert "C:\\Temp\\racs-v100-release-verify" in report
    assert (
        "docker compose -f C:\\Temp\\racs-v100-release-verify\\deploy\\compose.yaml down" in report
    )
    assert "未发布、未创建 Tag、未推送" in changelog


def test_current_release_record_closes_lockfile_and_records_frontend_pull_eof() -> None:
    report = (ROOT / "docs" / "release-validation-v1.0.0-2026-07-28.md").read_text(encoding="utf-8")

    current = report.split("## 当前发布状态", maxsplit=1)[1].split("## 阻塞处理结果", maxsplit=1)[0]
    assert "uv lock --check` 已通过" in current
    assert "docker pull docker/dockerfile:1" in current
    assert "读取 Docker Hub manifest 时返回 EOF" in current
    assert "Docker CLI 缺失" not in current
    assert "x-docker-expose-session-sharedkey" not in current


def test_latest_frontend_pull_failure_does_not_claim_services_are_healthy() -> None:
    report = (ROOT / "docs" / "release-validation-v1.0.0-2026-07-28.md").read_text(encoding="utf-8")

    latest = report.split("### Dockerfile frontend 预拉取", maxsplit=1)[1].split(
        "## 历史首次运行", maxsplit=1
    )[0]
    assert "退出码非零" in latest
    assert "未重新执行" in latest
    assert "健康/连通性检查" in latest
