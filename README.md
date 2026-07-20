# Recoverable AI Customer Service

RACS 是一个可恢复式 AI 售后客服项目。当前工程已完成 T-000 工程基线与 T-001 核心业务数据基线；尚未实现订单接口、政策检索、资格规则、Agent、工作流、审批或产品界面。

## 项目版本与发布

项目唯一版本号来源是 `pyproject.toml` 的 `[project].version`，当前为 `0.1.0`。阶段版本规划、发布门禁与一致性检查见 `docs/RELEASES.md`；已完成但尚未正式发布的变化见 `docs/CHANGELOG.md`；任务验收证据按 `docs/task-reports/T-xxx.md` 维护。

当前没有足够证据证明任何项目版本已经正式发布。`TASKS.md` 中的任务验收记录不自动等同于 Reviewer 通过或阶段正式发布。

## 版本基线

| 组件 | 基线 |
| --- | --- |
| Python | 3.12（`requires-python >=3.12,<3.13`） |
| Node.js | 24.18.0 LTS |
| pnpm | 11.9.0 |
| PostgreSQL | 17 |
| pgvector | 0.8.2 |
| Docker Compose | 2.24.0 或更高 |

Python 依赖的精确版本记录在 `uv.lock`，前端依赖的精确版本记录在 `pnpm-lock.yaml`。当前验证的核心兼容组合为 Pydantic 2.13.4、LangGraph 1.2.9 和 PostgreSQL checkpointer 3.1.0，并由后端锁文件与导入测试共同固定。

## 本地验证

```text
uv sync --frozen --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest

pnpm --dir web install --frozen-lockfile
pnpm --dir web format:check
pnpm --dir web lint
pnpm --dir web test
pnpm --dir web build

docker compose -f deploy/compose.yaml config
```

后端开发启动命令：

```text
uv run uvicorn customer_service.main:app --reload
```

存活检查为 `GET /health/live`。完整基础服务可使用 `docker compose -f deploy/compose.yaml up --build` 启动。

## 合成数据基线

版本化数据入口为 `data/manifest.json`，数据说明见 `data/README.md`。数据集版本 `1.0.0` 使用固定业务基准日 `2026-07-20`，覆盖正常退货、质量问题、边界日期、超期、高金额、订单不存在、订单越权以及有效、过期、无结果和冲突政策场景。

数据一致性专项验证：

```text
uv run pytest tests/data
```

这些文件只提供合成事实与设计用途，不包含 T-002 固定验收用例或任何业务处理功能。
