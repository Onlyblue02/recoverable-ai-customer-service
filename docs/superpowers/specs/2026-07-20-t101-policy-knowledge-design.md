# T-101 政策知识与引用回答设计

## 1. 目标与边界

T-101 基于 T-001 数据集 `racs-core-business-data` 版本 `1.0.0` 实现独立、确定性的政策问答组件。组件根据结构化商品类别、退货原因和查询日期，返回带实际政策来源的当前有效答案，或者返回可判断的证据不足、过期或冲突结果。

本任务不实现自然语言意图或字段抽取、HTTP API、数据库与向量索引、Agent、LangGraph、订单查询、资格规则、审批、界面或 T-102。自然语言抽取属于 T-201；当前任务使用 T-002 用例的 `semantic_intent` 与 `required_entities` 验证政策语义，不比较固定措辞。

## 2. 固定输入与假设

- 政策来源只允许使用 `data/manifest.json` 声明的 T-001 政策文件。
- 数据集版本固定为 `1.0.0`。
- 默认查询日期来自 T-001 manifest 的 `reference_date`，即 `2026-07-20`；组件不读取系统当天日期。
- 调用方提供结构化 `category`、可选 `return_reason` 和可选 `as_of`。
- 确定性答案只允许引用本次实际用于形成答案的当前有效政策。
- 过期或冲突政策可以记录为候选证据，但不能出现在支持确定性答案的 `citations` 中。

## 3. 方案选择

采用类型化 JSON 政策目录与确定性问答服务，不新增运行时依赖。

完整 PostgreSQL/pgvector 实现需要 SQLAlchemy、Alembic、Embedding Gateway、迁移和集成环境，但当前固定政策只有五条，T-101 验收不要求自然语言向量召回。仓储协议加 JSON/PostgreSQL 双实现同样没有当前验收价值。文件目录方案直接消费已发布的 T-001 事实，范围最小，并可在后续语义检索任务中替换数据访问实现。

本选择有意不创建 `infrastructure/database` 和 `migrations`。它满足 T-101 的业务输出，但不代表最终 PostgreSQL/pgvector 知识架构已经实现。

## 4. 组件设计

### `rag/schemas.py`

定义不可变、类型化对象：

- `PolicyDocument`：政策 ID、版本、标题、来源、状态、有效期、适用类别、原因、决定和内容。
- `PolicyQuery`：类别、原因和查询日期。
- `PolicyCitation`：实际支持答案的政策 ID、版本、标题、来源、有效期和内容摘录。
- `PolicyAnswerResult`：状态、推荐动作、答案、引用、候选政策 ID 和原因。

结果状态：

- `ANSWERED`：存在充分、无冲突的当前政策证据。
- `INSUFFICIENT_EVIDENCE`：只有过期政策、完全无结果、缺少必要原因或多来源仍含糊。
- `CONFLICT`：当前有效来源的决定互相冲突。

推荐动作：

- `ANSWER`：发送确定性答案。
- `CLARIFY`：说明缺少当前依据并请求补充或人工协助。
- `ESCALATE`：政策冲突，需要人工确认。

### `rag/catalog.py`

从 T-001 manifest 加载所有含 `policies` 集合的文件，验证文件存在、数据集版本一致和政策 ID 唯一，并把 JSON 转换成 `PolicyDocument`。

目录提供确定性筛选：先按类别和退货原因找相关政策，再按 `published` 状态及包含性有效期判断当前政策。筛选不读取系统时间，不执行模糊或向量匹配。

### `rag/service.py`

协调政策目录并生成最终结果。处理顺序：

1. 查找类别和原因相关的全部政策。
2. 类别存在多种相关原因而查询未提供原因时，返回 `INSUFFICIENT_EVIDENCE / CLARIFY / MISSING_RETURN_REASON`。
3. 过滤查询日期当前有效且状态为 `published` 的政策。
4. 无当前政策但存在过期匹配时，返回 `INSUFFICIENT_EVIDENCE / CLARIFY / EXPIRED_ONLY`。
5. 没有任何匹配时，返回 `INSUFFICIENT_EVIDENCE / CLARIFY / NO_RESULT`。
6. 当前政策的 `decision` 不一致时，返回 `CONFLICT / ESCALATE / CONFLICTING_POLICIES`，且 `answer` 和 `citations` 为空。
7. 存在多份决定相同但内容不同的当前政策时，返回 `INSUFFICIENT_EVIDENCE / CLARIFY / AMBIGUOUS_SOURCES`，不自行定义优先级。
8. 恰好一份当前政策充分匹配时，用确定性模板组织政策标题与内容，返回 `ANSWERED / ANSWER`，并为该实际使用来源创建引用。

任何非 `ANSWERED` 结果都不得包含“可以退”“不能退”等确定性答案。

## 5. 引用与安全约束

- `citations` 中的政策必须同时存在于本次当前有效候选集合和答案使用集合。
- 引用至少包含政策 ID、版本、标题、`source`、有效期和内容摘录。
- 答案不得引用过期政策、未检索政策或调用方提供的伪造来源。
- `ANSWERED` 必须包含非空答案和至少一条引用。
- 非 `ANSWERED` 必须使答案和引用为空，并通过原因与推荐动作说明下一步。
- 冲突结果保留完整候选政策 ID，便于后续人工审批任务使用，但 T-101 不创建审批记录。

## 6. T-002 验收映射

组件测试读取 `data/evaluation/retrieval/cases.v1.json`，不复制用例事实：

| 用例 | 预期组件结果 |
| --- | --- |
| `AC-FR03-N-001` | `ANSWERED`；答案包含七日条件；引用 `POL-ACTIVE-STANDARD-001` 的实际 `source` |
| `AC-FR03-E-001` | `INSUFFICIENT_EVIDENCE / EXPIRED_ONLY`；无确定性答案 |
| `AC-FR03-E-002` | `INSUFFICIENT_EVIDENCE / NO_RESULT`；无确定性答案 |
| `AC-FR03-E-003` | `CONFLICT / ESCALATE`；完整保留两份冲突政策 ID；无确定性答案 |
| `AC-FR09-E-001` | 无政策依据时不能生成确定性结论或虚构引用 |

测试使用 `required_entities` 构造结构化查询，并校验用例要求的唯一终态语义，不以 `utterance_examples` 完整字符串相等作为通过条件。

## 7. 测试设计

单元测试覆盖：

- manifest 加载、版本一致性和政策 ID 唯一性；
- 发布状态、有效期包含边界、类别和原因过滤；
- 当前有效政策的确定性答案与实际引用；
- 过期、无结果、冲突及多来源含糊的安全拒答；
- 答案引用集合与实际使用政策集合完全一致；
- 默认固定基准日不依赖系统日期；
- 缺失文件、版本不一致和重复 ID 明确失败。

组件测试覆盖上述五个 T-002 政策相关用例。实现完成后运行 T-101 专项测试、T-001/T-002 基线测试、全仓 pytest、Ruff 和 mypy；前端和 Compose 未发生修改，但按现有全仓质量口径复核。

## 8. 预计文件

实现：

- `src/customer_service/rag/__init__.py`
- `src/customer_service/rag/schemas.py`
- `src/customer_service/rag/catalog.py`
- `src/customer_service/rag/service.py`

测试：

- `tests/unit/rag/test_policy_service.py`
- `tests/component/rag/test_policy_acceptance_cases.py`

记录：

- `README.md`
- `TASKS.md`
- `docs/task-reports/T-101.md`
- `docs/CHANGELOG.md`
- 本设计文档

不修改 T-001/T-002 数据和验收用例，不修改项目版本，不创建阶段 Tag，不推送远程。

## 9. 验收与发布状态

执行者测试通过后，T-101 状态只能记录为“待 Reviewer”。`docs/CHANGELOG.md` 的 `Unreleased` 记录已经实现且可核实的能力，不创建 `v0.3.0` 正式条目。T-101 完成不代表 T-102、自然语言 Agent、数据库向量检索或阶段二全部能力已经完成。
