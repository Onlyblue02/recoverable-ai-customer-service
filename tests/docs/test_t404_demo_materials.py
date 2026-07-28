from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_t404_demo_materials_link_real_startup_and_evidence() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    startup = (ROOT / "docs/demo/STARTUP.md").read_text(encoding="utf-8")
    script = (ROOT / "docs/demo/DEMO_SCRIPT.md").read_text(encoding="utf-8")

    assert "docs/demo/STARTUP.md" in readme
    assert "docs/demo/DEMO_SCRIPT.md" in readme
    assert "uv run uvicorn customer_service.main:app" in startup
    assert "pnpm --dir web dev" in startup
    assert "ORD-NORMAL-001" in script
    assert "ORD-HIGH-VALUE-001" in script
    assert "T204-T203-GROUNDED-REWRITE-001" in script
    assert "DEEPSEEK_API_KEY" in startup


def test_t404_demo_materials_disclose_unverified_compose_and_fixed_scope() -> None:
    startup = (ROOT / "docs/demo/STARTUP.md").read_text(encoding="utf-8")
    script = (ROOT / "docs/demo/DEMO_SCRIPT.md").read_text(encoding="utf-8")
    vite = (ROOT / "web/vite.config.ts").read_text(encoding="utf-8")

    assert "Compose" in startup and "尚未完成" in startup
    assert "10" in script and "38" in script
    assert "DeepSeek" in script
    assert '"/api"' in vite and "http://127.0.0.1:8000" in vite
