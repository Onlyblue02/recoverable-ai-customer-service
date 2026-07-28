# RACS 固定验收用例集

- 用例集版本：`1.0.0`
- 依赖数据集：`racs-core-business-data` `1.0.0`
- 固定基准日：`2026-07-20`
- Schema：`schema/acceptance-suite.schema.json`

用例按 routing、retrieval、rules、graph、experience 和 e2e 分组。每个用例定义前置条件、结构化输入语义、两条可替换示例措辞、有序期望过程和唯一结构化终态。

示例措辞不是精确匹配条件。未来运行器必须依据 `semantic_intent`、`required_entities` 和可观察断言判断结果。

本目录只定义验收契约，没有运行政策检索、订单查询、资格判断、审批、恢复或界面测试。Schema 和一致性检查通过不等于业务能力通过。

验证命令：

```text
uv run pytest tests/evaluation -q
```

## T-403 可重复验收报告

T-403 使用本目录的固定版本和既有公开服务路径生成代表性运行报告，不修改本验收契约。运行命令：

```text
.venv\Scripts\python.exe -m customer_service.acceptance_reporting.runner --output reports/evaluations/t403-fixed-acceptance.json
```

运行产物位于被 Git 忽略的 `reports/evaluations/`；可审计摘要见 `docs/acceptance/T-403-fixed-acceptance-report.md`。`failures/cases.v1.json` 保留真实历史失败及改进建议，不能被通过结果覆盖。
