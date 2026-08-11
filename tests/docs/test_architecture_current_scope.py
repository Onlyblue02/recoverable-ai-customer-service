from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_architecture_documents_state_the_current_in_memory_demo_boundary() -> None:
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    structure = (ROOT / "docs" / "PROJECT_STRUCTURE.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    startup = (ROOT / "docs" / "demo" / "STARTUP.md").read_text(encoding="utf-8")

    for document in (architecture, structure, readme):
        assert "进程内" in document
        assert "SSE" in document

    assert "当前没有生产认证、持久数据库、PostgreSQL、迁移、SSE/EventSource" in architecture
    assert "没有 PostgreSQL 数据库、数据库迁移、SSE/EventSource" in structure
    assert "agent_workflow/" in structure
    assert "单一受控进程内入口" in structure
    assert "不是通用 Agent 平台" in structure
    assert "持久数据库" in readme
    assert "进程内合成状态" in startup


def test_architecture_and_structure_mark_future_capabilities_as_unimplemented() -> None:
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    structure = (ROOT / "docs" / "PROJECT_STRUCTURE.md").read_text(encoding="utf-8")

    assert "未来规划（未实现）" in architecture
    assert "完整 LangGraph 工作流、Agent" in architecture
    assert "未来目标结构（未实现）" in structure
    assert "interfaces/sse.py" in structure
    assert "当前不存在或未接入运行路径" in structure


def test_t404_delivery_documents_keep_real_demo_and_release_limits() -> None:
    startup = (ROOT / "docs" / "demo" / "STARTUP.md").read_text(encoding="utf-8")
    script = (ROOT / "docs" / "demo" / "DEMO_SCRIPT.md").read_text(encoding="utf-8")
    report = (ROOT / "docs" / "task-reports" / "T-404.md").read_text(encoding="utf-8")

    assert "uv run python -m customer_service.local_server" in startup
    assert "ORD-NORMAL-001" in script
    assert "ORD-HIGH-VALUE-001" in script
    assert "T204-T203-GROUNDED-REWRITE-001" in script
    assert "Docker BuildKit 构建" in report
    assert "最终结论：PASS；允许创建 T-404 普通任务提交，当前不发布 `v1.0.0`" in report
