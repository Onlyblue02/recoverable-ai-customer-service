import hashlib
import json
import subprocess
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


def test_production_web_proxies_agent_api_to_controlled_backend() -> None:
    dockerfile = (ROOT / "deploy" / "web.Dockerfile").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    assert "COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf" in dockerfile
    assert "location /api/" in nginx
    assert "proxy_pass http://racs-api:8000;" in nginx
    assert "try_files $uri $uri/ /index.html;" in nginx


def test_release_record_proves_named_volume_cleanup() -> None:
    record = (ROOT / "docs" / "release-validation-docker-2026-08-11.md").read_text(encoding="utf-8")

    assert "down --volumes --remove-orphans" in record
    assert "docker volume inspect racsverify20260811_postgres-data" in record
    assert "no such volume" in record
    assert "精确名称过滤的 `docker volume ls`" in record
    assert "项目容器、网络和命名卷均无残留" in record


def test_t608_docker_revalidation_records_real_web_agent_chain_and_cleanup() -> None:
    record = (ROOT / "docs" / "release-validation-docker-2026-08-11.md").read_text(encoding="utf-8")

    assert "5b24609fba10ce9a189c06f8b0da87efda0082ea" in record
    assert "LogicalBlobMismatches" not in record
    assert "0 mismatch" in record
    assert "Web 同源 `/api/v1/agent/modes`" in record
    assert "RESPONSE_GATE_ALLOWED" in record
    assert "DeepSeek `configured=false`" in record
    assert "真实模型 Docker 路径未执行" in record
    assert "docker compose -p racsverify5b24609" in record
    assert "racsverify5b24609_postgres-data" in record
    assert "其他项目的三个既有容器 ID 完全一致" in record

    evidence = (ROOT / "docs" / "evaluations" / "docker-compose-5b24609-validation.log").read_text(
        encoding="utf-8"
    )
    assert "git_revision=5b24609fba10ce9a189c06f8b0da87efda0082ea" in evidence
    assert "web_agent_modes_status=200" in evidence
    assert "deepseek_http_evaluation=NOT_EXECUTED" in evidence
    assert "project_containers_remaining=0" in evidence
    assert "other_container_ids_unchanged=true" in evidence


def test_post_fix_manifest_binds_working_tree_docker_inputs() -> None:
    manifest = json.loads(
        (ROOT / "docs" / "evaluations" / "docker-compose-5b24609-post-fix-manifest.json").read_text(
            encoding="utf-8-sig"
        )
    )
    entries = {entry["path"]: entry for entry in manifest["entries"]}

    assert manifest["manifest_version"] == "docker-post-fix-input-v2"
    assert manifest["base_revision"] == "5b24609fba10ce9a189c06f8b0da87efda0082ea"
    assert len(entries) == 142
    for path in ("deploy/nginx.conf", "deploy/web.Dockerfile"):
        assert entries[path]["source"] == "working-tree"
        assert entries[path]["sha256"] == hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    for path, entry in entries.items():
        if entry["source"] != "HEAD":
            continue
        blob = subprocess.check_output(
            ["git", "show", f"{manifest['base_revision']}:{path}"], cwd=ROOT
        )
        assert entry["sha256"] == hashlib.sha256(blob).hexdigest()
        assert entry["size"] == len(blob)

    assert entries["deploy/compose.yaml"]["sha256"] == (
        "c0b474708af0605de214682bf9c17587805b3fb822fad558040016b5a35864c2"
    )
    assert entries["deploy/backend.Dockerfile"]["sha256"] == (
        "a639146d1f96a601ca529cbdde278c8d9bdb354eda0df552d05cd5d93d538586"
    )

    encoded = json.dumps(manifest["entries"], ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    assert manifest["post_fix_digest"] == hashlib.sha256(encoded).hexdigest()

    record = (ROOT / "docs/release-validation-docker-2026-08-11.md").read_text(encoding="utf-8")
    assert manifest["post_fix_digest"] in record
    assert "基础 commit 单独表述为修复后完整输入" in record
