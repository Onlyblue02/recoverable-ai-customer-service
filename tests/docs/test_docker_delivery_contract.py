from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_backend_image_contains_runtime_data_and_config() -> None:
    dockerfile = (ROOT / "deploy" / "backend.Dockerfile").read_text(encoding="utf-8")

    assert "COPY config ./config" in dockerfile
    assert "COPY data ./data" in dockerfile
    assert dockerfile.index("COPY data ./data") < dockerfile.index("COPY src ./src")


def test_compose_host_ports_are_overridable_without_changing_container_ports() -> None:
    compose = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    assert '"${RACS_BACKEND_PORT:-8000}:8000"' in compose
    assert '"${RACS_MOCK_BUSINESS_PORT:-8001}:8001"' in compose
    assert '"${RACS_WEB_PORT:-5173}:80"' in compose
    assert "/health/live" in compose
    assert "pg_isready" in compose


def test_release_record_proves_named_volume_cleanup() -> None:
    record = (ROOT / "docs" / "release-validation-docker-2026-08-11.md").read_text(encoding="utf-8")

    assert "down --volumes --remove-orphans" in record
    assert "docker volume inspect racsverify20260811_postgres-data" in record
    assert "no such volume" in record
    assert "精确名称过滤的 `docker volume ls`" in record
    assert "项目容器、网络和命名卷均无残留" in record
