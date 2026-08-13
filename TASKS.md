# Product Delivery Tasks

## 1. 文档目的

本文记录第一版本已执行任务及后续经批准的规划任务，使其可以依次交给 Codex 实现和验收。除工程或架构设计任务负责落实已批准技术文档中的基线外，其余任务只规定目标、输入、输出、依赖和验收结果，不自行重写产品需求或扩大范围。

## 2. 执行原则

- 严格按依赖顺序逐项执行，当前任务验收通过后再进入下一项。
- 每个任务只实现达成自身验收标准所需的最小范围。
- 优先形成可运行的纵向业务结果，不同时铺开多个未闭环模块。
- 每个任务完成后，记录修改内容、验证方式、实际结果和未覆盖风险。
- 发现需求冲突或需要扩大范围时，先停止实现并说明影响，不自行增加功能。
- 所有业务数据均为合成数据，不包含真实用户信息或资金操作。

## 3. 阶段划分

| 阶段 | 阶段目标 | 阶段出口 |
| --- | --- | --- |
| 阶段一：工程与产品基线 | 建立最小可验证工程入口、统一业务口径和可验收数据 | 工程基线可重复验证，核心场景、规则和固定用例可直接用于开发 |
| 阶段二：基础业务能力 | 分别完成政策、订单、资格和模拟申请能力 | 单项能力可独立验证 |
| 阶段三：AI 售后流程 | 完成诉求识别、多轮收集和标准退货闭环 | 标准退货流程可重复运行 |
| 阶段四：人工协作与恢复 | 完成高风险审批、中断恢复和质量门禁 | 高风险流程可安全完成且不重复执行 |
| 阶段五：界面与交付验证 | 完成用户界面、验收集和演示材料 | 项目形成可展示、可验证的作品集闭环 |
| 阶段六：Agent MVP | 在现有确定性组件之上增加受控 Agent 规划、工具执行和可信回复 | Agent 正常与对抗用例可重复验证，且不突破确定性裁决边界 |

### 阶段版本规划与发布记录

| 计划版本 | 任务范围 | 阶段目标 |
| --- | --- | --- |
| `v0.1.0` | T-000 | 工程基线 |
| `v0.2.0` | T-001～T-002 | 产品基线 |
| `v0.3.0` | T-101～T-104 | 基础业务能力 |
| `v0.4.0` | T-201～T-204 | AI 售后流程与模型适配 |
| `v0.5.0` | T-301～T-304 | 人工协作与恢复 |
| `v1.0.0` | T-401～T-404 | 完整 MVP |

以上是规划映射，不代表任务完成、Reviewer 通过或版本已发布。项目唯一版本号来源、正式发布门禁和当前发布状态见 `docs/RELEASES.md`；版本变化见 `docs/CHANGELOG.md`；任务证据按 `docs/task-reports/T-xxx.md` 维护。任务完成只使其具备进入 Reviewer 审查的条件，不能自动触发正式发布。

## 4. 阶段一：工程与产品基线

### T-000 工程基线与最小骨架

**完成状态**

- [x] 2026-07-19 验收通过。
- 修改：建立 Python/FastAPI 与 React/Vite 最小骨架、类型化配置、唯一后端和前端锁文件、质量命令、CI、Dockerfile 与四服务 Compose 基础配置。
- 验证：`uv sync --frozen --all-groups`、Ruff format/check、mypy、pytest（3 passed）、后端真实启动与 `/health/live`、`pnpm install --frozen-lockfile`、Prettier、peer dependency、ESLint、Vitest（1 passed）、TypeScript/Vite build、`docker compose config` 全部通过。
- 范围：未加入合成业务数据、业务数据库模型、政策检索、Mock 订单接口、Agent、工作流、审批或产品界面功能。

**任务目标**

在实现业务数据和产品能力前，建立可重复安装、运行和验证的最小工程基线，避免后续任务同时处理环境、目录和业务问题。

**输入**

- `ARCHITECTURE.md` 中的模块边界与部署单元。
- `TECH_STACK.md` 中的运行时、包管理、质量工具、数据库和容器选型。
- `docs/PROJECT_STRUCTURE.md` 中的目标目录与按需创建原则。

**输出**

- 固定的 Python、Node.js、pnpm、PostgreSQL/pgvector 和 Docker Compose 版本基线。
- 后端可导入的最小包与存活检查入口，以及可构建的前端空壳；不包含产品界面或业务行为。
- 后端与前端依赖清单及唯一锁文件、类型化配置入口和环境变量示例。
- 最小测试、格式化、静态检查和 CI 命令。
- 可校验的 Docker Compose 基础配置，不包含业务数据初始化。

**验收标准**

- 干净环境可依据锁文件完成后端和前端依赖安装。
- 后端最小应用可启动并通过存活检查，前端空壳可完成构建。
- 格式化、静态检查和最小测试命令可运行，CI 至少执行这些命令。
- Docker Compose 配置可通过语法和服务配置校验。
- 不包含合成业务数据、业务数据库模型、政策检索、Mock 订单接口、Agent、工作流、审批或产品界面功能。

### T-001 核心业务数据与场景基线

**完成状态**

- [x] 2026-07-20 验收通过。
- 修改：新增版本为 `1.0.0`、固定业务基准日为 `2026-07-20` 的合成用户、商品、订单、已有模拟售后申请和政策数据；覆盖正常退货、质量问题、7 天边界、8 天超期、高金额、订单不存在、订单越权、当前有效政策、过期政策、无结果和互相冲突政策，并记录每条关键数据的业务用途与预期行为。
- 验证命令：`uv run pytest tests/data -q`；`uv run ruff format --check .`；`uv run ruff check .`；`uv run mypy src tests`；`uv run pytest`。
- 实际结果：T-001 数据专项测试 9 项通过；全仓测试 12 项通过；Ruff 与 mypy 通过；数据版本、文件清单、标识唯一性、实体引用、金额、日期、订单归属、商品类别、政策有效期、冲突范围、无结果场景和合成身份约束均通过自动检查；确认未创建 `data/evaluation`。
- 未覆盖风险：数据尚未导入数据库，数据库模型、迁移和 seed 执行器由后续任务实现；高金额阈值与退货资格结论尚未由 T-103 固化；政策尚未经过 T-101 的导入、检索和引用验证；固定验收用例属于 T-002，当前未实现；后续若改变固定基准日或业务事实，应发布新数据版本而不是改写 `1.0.0` 语义。

**任务目标**

建立后续所有功能和验收共用的合成数据，避免开发过程中临时改变业务事实。

**输入**

- `PROJECT.md` 中的五类使用场景。
- `REQUIREMENTS.md` 中的订单、政策、退货与风险要求。
- 当前、过期、冲突政策以及正常、边界、越权、高金额订单的覆盖要求。

**输出**

- 合成用户、订单、商品、政策和售后申请数据。
- 每条关键数据的业务用途和预期行为说明。
- 数据版本标识。

**验收标准**

- 数据至少覆盖正常退货、质量问题、边界日期、超期、高金额、订单不存在和订单越权。
- 政策同时包含当前有效、过期、无结果和互相冲突的样本。
- 数据之间不存在订单归属、日期或政策适用范围矛盾。
- 数据不包含真实个人信息。

### T-002 固定验收用例

**完成状态**

- [x] 2026-07-20 Reviewer 复审通过；阶段一结论为 PASS，允许发布 `v0.2.0` 并进入 T-101。
- 修改：基于 T-001 数据集 `1.0.0` 建立固定验收集 `1.0.0`，共 38 个用例；覆盖 FR-01～FR-12 每项至少一个正常用例和一个异常或边界用例，包含政策问答、订单查询与越权、退货资格、人工审批、中断恢复、无依据回答、虚假完成和审批绕过，并固定标准退货及高风险审批恢复两条端到端故事；新增 Draft 2020-12 JSON Schema、清单和一致性测试。
- Reviewer 修复：Schema 现在拒绝空语义对象、含糊短文本和纯空白内容；自动门禁校验普通用例 ID 与需求映射，并逐场景验证有效、过期、无结果和冲突政策与 T-001 的商品、类别、有效期、状态及完整政策集合关系。新增负例先复现 12 个预期失败，再完成修复。
- 验证命令：`uv lock --check`；`uv run pytest tests/evaluation -q`；`uv run pytest tests/data tests/evaluation -q`；`uv run ruff format --check .`；`uv run ruff check .`；`uv run mypy src tests`；`uv run pytest`；前端 install/format/lint/test/build；`docker compose -f deploy/compose.yaml config --quiet`。
- 实际结果：T-002 专项测试 25 项通过；阶段一数据与验收测试 34 项通过；全仓 Python 测试 37 项通过并有 1 条上游弃用警告；Ruff format/check、mypy、锁文件、前端 1 项测试与构建、Compose 配置检查均通过。Reviewer 已复审阻塞修复并给出 PASS。
- Reviewer 结论：2026-07-20 阶段一复审 PASS，允许发布 `v0.2.0`，允许进入 T-101；证据为项目所有者在 Release Manager 任务中的正式确认。
- 未覆盖风险：用例仍是功能实现前的静态验收合同，尚未由 T-101 及后续业务能力执行；自然语言尚未验证真实模型改写鲁棒性；界面、审批持久化、中断恢复和业务副作用仅定义可观察期望；缺少 CI 链接；历史 T-001 提交未形成独立任务级边界。

**任务目标**

在功能实现前定义“什么算完成”，防止只按理想演示结果开发。

**输入**

- T-001 合成数据。
- REQUIREMENTS.md 中全部 P0 功能和验收标准。

**输出**

- 政策问答、订单查询、退货规则、人工审批、恢复和安全边界用例。
- 每个用例的前置条件、用户输入、期望过程和期望终态。
- 标准退货和高风险审批两条端到端故事。

**验收标准**

- 每项 P0 功能至少对应一个正常用例和一个异常或边界用例。
- 每个用例只有一个明确、可判断的预期结果。
- 包含越权、无依据回答、虚假完成状态和审批绕过用例。
- 用例不依赖固定自然语言措辞才能通过。

## 5. 阶段二：基础业务能力

### T-101 政策知识与引用回答

**完成状态**

- [x] 2026-07-20 Reviewer 最终复审 PASS；政策引用安全遗留项已关闭，允许提交 T-101 并进入 T-102。
- 修改：新增基于 T-001 数据集 `1.0.0` 的类型化 JSON 政策目录和确定性问答服务；按商品类别、退货原因、发布状态及包含性有效期筛选政策；当前有效且唯一明确的政策生成带实际 ID、版本、标题、来源、有效期和内容摘录的答案；过期、无结果、冲突、缺少退货原因或多来源含糊时返回结构化澄清/升级结果且不生成确定性结论。
- 固定用例：组件测试直接读取 T-002 的 `AC-FR03-N-001`、`AC-FR03-E-001/002/003` 和 `AC-FR09-E-001`，使用 `required_entities` 构造查询，不依赖固定自然语言字符串。
- 验证命令：`uv lock --check`；`uv run pytest tests/unit/rag tests/component/rag -q`；`uv run pytest tests/data tests/evaluation -q`；`uv run ruff format --check .`；`uv run ruff check .`；`uv run mypy src tests`；`uv run pytest`；前端冻结安装、格式、lint、测试与构建；`docker compose -f deploy/compose.yaml config --quiet`。
- 安全收尾：公开 `PolicyAnswerService.answer()` 在返回前将政策 ID、证据 ID、版本、来源、有效期和内容绑定到本次实际检索并使用的当前政策；绑定失败时安全降级为 `UNGROUNDED_CITATION`，不公开答案或引用；新增 6 项公开路径伪造引用回归测试。
- 实际结果：实现前测试因缺少 `customer_service.rag` 出现 2 个预期收集错误；初始实现后 T-101 专项测试 19 项通过；安全修复后伪造引用回归 6 项通过、T-101 专项 25 项通过、阶段一基线 34 项通过、全仓 Python 测试 62 项通过；22 个 Python 文件格式检查、Ruff 和 mypy 通过。Reviewer 最终复审 PASS。
- Reviewer 结论：2026-07-20 最终复审 PASS，政策引用安全遗留项关闭；证据为项目所有者在 Release Manager 任务中的正式确认。
- 未覆盖风险：仅支持结构化类别/原因输入和精确属性过滤；尚无自然语言抽取、HTTP API、PostgreSQL/pgvector、持久化证据快照、Agent 或界面；冲突只返回升级建议，不创建审批任务；当前只有本地测试证据，没有 CI 链接；通用最终回复门禁仍属于 T-303。

**任务目标**

让用户获得基于当前有效政策、带来源且能够安全拒答的答案。

**输入**

- T-001 政策数据。
- 用户政策问题。
- 政策有效期、状态和适用类别。

**输出**

- 政策答案或证据不足状态。
- 支持答案的来源信息。
- 过期、冲突或无结果原因。

**验收标准**

- 当前有效政策问题返回正确答案和来源。
- 过期政策不作为当前结论。
- 无结果或来源冲突时不生成确定性答案。
- 输出引用只能来自本次实际使用的政策内容。

### T-102 订单查询与权限边界

**完成状态**

- [x] 2026-07-22 Reviewer 最终审查 PASS；允许创建 T-102 普通任务提交并进入 T-103，当前不发布阶段版本。
- 修改：新增基于 T-001 数据集 `1.0.0` 的固定 JSON 订单仓库、Mock Business 订单 HTTP API、客户服务 HTTP Gateway 和公开 `OrderQueryService.query()`；公开 payload 仅允许 `order_id`，可信 `user_id` 由独立服务端 `OrderAccessContext` 注入；订单存在性与归属在可信仓库边界判定；不存在与越权公开响应统一防枚举；下游异常稳定安全降级；成功响应按显式订单/商品字段白名单转换。
- 固定用例：组件测试直接读取并执行 T-002 的 `AC-FR04-N-001`、`AC-FR04-E-001/002/003`，覆盖已授权成功、缺少订单号、不存在和越权，且不依赖完全固定的用户措辞。
- 验证命令：`.venv\\Scripts\\pytest.exe tests/unit/tools tests/unit/mock_business tests/component/tools -q -p no:cacheprovider --basetemp=.pytest-tmp-t102-targeted`；`.venv\\Scripts\\pytest.exe tests/data tests/evaluation tests/unit/rag tests/component/rag -q -p no:cacheprovider --basetemp=.pytest-tmp-stage-baseline`；`.venv\\Scripts\\pytest.exe -q -p no:cacheprovider --basetemp=.pytest-tmp-full`；`.venv\\Scripts\\ruff.exe format --check .`；`.venv\\Scripts\\ruff.exe check .`；`.venv\\Scripts\\mypy.exe src tests`；`uv lock --check --offline --cache-dir .uv-cache-t102`；前端 format/lint/test/build；`docker compose -f deploy/compose.yaml config --quiet`。
- Reviewer 修复回归：新增公开 payload 身份/授权字段拒绝、可信上下文不可覆盖、同订单双身份、RuntimeError 脱敏、HTTP 超时/连接失败、无效 JSON、意外状态、错误码不匹配、公开防枚举及仓库内部状态保留测试。
- 第二轮修复：HTTP Gateway 将成功响应 `order_id` 严格绑定到服务实际发送的规范化请求 ID；不匹配时不返回 `FOUND`，而是进入现有 `dependency_failure/ORDER_LOOKUP_UNAVAILABLE` 脱敏路径。新增真实 `OrderQueryService -> HttpOrderGateway` 串单与空格规范化回归测试。
- 实际结果：串单安全回归文件 10 项、T-102 专项 36 项、阶段一与 T-101 基线 59 项、全仓 98 项均通过；35 个 Python 文件格式检查、Ruff lint、mypy、锁文件检查、前端格式/lint、1 项测试与构建均通过；保留 1 条 Starlette TestClient 上游弃用警告。当前会话未找到 Docker CLI，因此 Compose 配置检查未执行成功，不记录为通过。
- Reviewer 结论：最终审查 PASS；允许创建 T-102 普通任务提交并进入 T-103；当前不发布阶段版本。证据为项目所有者在 Release Manager 任务中的正式确认。
- 未覆盖风险：当前仅提供同步内部组件与 Mock Business API，未接入真实数据库、完整身份认证中间件、重试/熔断、监控或外部业务系统；授权模型只有固定数据中的单一订单所有者，不覆盖客服代查、共享账户或组织级授权；自然语言订单号抽取、退货资格、Agent 工作流和界面不在 T-102；当前只有本地执行证据且没有 CI 链接；Docker Compose 配置需在可解析 `docker` CLI 的环境补验。

**任务目标**

提供售后判断需要的订单事实，并阻止无权访问其他用户订单。

**输入**

- 当前用户身份。
- 用户提交的订单号。
- T-001 订单数据。

**输出**

- 已授权订单事实，或结构清晰的缺失、不存在、越权结果。

**验收标准**

- 用户只能查看属于自己的订单。
- 缺少订单号时要求补充，不执行查询结论。
- 不存在与越权结果不泄露订单详情。
- 返回结果不包含数据源中不存在的字段。

### T-103 退货资格规则

**完成状态**

- [x] 2026-07-23 Reviewer 最终审查 PASS；允许创建 T-103 普通任务提交并进入 T-104，当前不发布 `v0.3.0`。
- 修改：新增规则版本 `1.0.0` 的资格配置、冻结类型化输入输出、确定性 Eligibility Engine，并为 T-101 政策文档保留 T-001 已有的退货窗口字段；高金额阈值固定为 CNY `5000.00`（包含边界）。
- 规则：普通可再次销售商品在 7 个自然日包含性窗口内为低风险符合；质量问题使用 30 日政策并等待事实核验；普通超期、高金额、政策冲突或证据异常要求人工审批；缺少原因、商品状态、问题代码、签收日期或目标商品时返回缺失项，不猜测。
- 固定用例：组件测试通过已授权订单服务、T-001 商品与政策数据和公开 Eligibility Engine 执行 T-002 的 `AC-FR06-N-001/002`、`AC-FR06-B-001`、`AC-FR06-E-001/002`。
- Reviewer 修复：唯一政策的 `decision` 现在是资格判断的强制门禁；普通原因仅支持 `allow_if_resalable`，质量原因仅支持 `allow_after_issue_verification`，明确 `deny` 返回确定性不符合资格，未知或原因/决策错配返回 `requires_approval/POLICY_EVIDENCE_INSUFFICIENT`。新增 7 项公开引擎对抗及保留回归测试。
- Reviewer 第二轮修复：高金额与超期风险在唯一政策 decision 之前收集；任一已知高风险不会被 `deny`、未知或原因/决策错配覆盖。多风险结果固定按 `OVERDUE_EXCEPTION`、`HIGH_VALUE_ORDER` 排序；低金额且窗口内的 `deny` 仍确定性不符合资格。新增 6 项公开引擎高风险优先级回归测试。
- 验证命令：`.venv\\Scripts\\pytest.exe tests/unit/eligibility tests/component/eligibility -q`；`.venv\\Scripts\\pytest.exe tests/data tests/evaluation tests/unit/rag tests/component/rag tests/unit/tools tests/unit/mock_business tests/component/tools -q`；`.venv\\Scripts\\pytest.exe -q`；Ruff format/check；mypy；`uv lock --check --offline --cache-dir .uv-cache-t103`；前端 format/lint/test/build；Compose 配置检查。
- 实际结果：初始实现前专项测试出现 3 个预期模块缺失收集错误；第一轮 Reviewer 对抗测试修复前复现 5 个失败路径；第二轮高风险优先级回归修复前复现 6 个失败路径。最终 T-103 专项 39 项、既有阶段基线 95 项、全仓 137 项通过；42 个 Python 文件格式检查、Ruff lint、mypy、65 包锁文件检查、前端格式/lint、1 项测试和构建通过；保留 1 条 Starlette TestClient 上游弃用警告。当前会话无法识别 Docker CLI，Compose 未执行成功且未记录为通过。
- Reviewer 结论：2026-07-23 最终审查 PASS；允许创建 T-103 普通任务提交并进入 T-104，当前不发布 `v0.3.0`。证据为项目所有者在 Release Manager 任务中的正式确认。
- 未覆盖风险：质量事实仅标记待核验，不执行核验；规则仅覆盖当前固定原因、类别、CNY 阈值和单目标商品；尚未接入真实认证/数据库、审批持久化、自然语言抽取、Agent 或工作流；当前只有本地验证证据，没有 CI 链接；Docker Compose 配置需在可解析 `docker` CLI 的环境补验。

**任务目标**

使用明确、可重复的业务规则判断退货资格和风险，而不是让 AI 自由决定。

**输入**

- 已授权订单事实。
- 退货原因和商品状态。
- 当前政策及业务阈值。

**输出**

- 资格结论。
- 命中的业务规则。
- 缺失信息。
- 风险原因和是否需要人工审批。

**验收标准**

- 普通退货、质量问题、边界日期、超期和高金额均得到预期结果。
- 输入相同则输出一致。
- 信息不足时返回缺失项，不猜测结论。
- 高风险条件必定要求人工审批。

### T-104 模拟售后申请与重复保护

**完成状态**

- [x] 2026-07-23 Reviewer 阶段二最终复审 PASS；允许发布 `v0.3.0` 并进入 T-201。
- 修改：新增公开 `ServiceCaseService.create()`、冻结 Schema、服务端身份上下文、可注入的进程内模拟申请仓库及 T-001 现有申请种子导入。只有已授权订单、绑定商品行和低风险 `eligible` 资格结果可创建申请；公开响应使用明确白名单。
- 幂等：内部键由可信 `user_id + order_id + order_item_id` 规范化派生；公开 payload 不得指定 `workflow_id`、幂等键或资格结论。重复调用返回同一首次确认记录，不产生第二条申请；T-001 的 `SC-DEMO-001` 也以同一可信键映射复用，不改写版本化数据。
- Reviewer 修复：资格结论现由独立服务端 `ServiceCaseEligibilityContext` 注入，且 T-103 `EligibilityResult` 绑定实际订单、商品行、产品和规则版本。T-104 在写入前逐字段核对绑定；existing 与 created 均要求最终 `created` 状态及用户、订单、商品行和键完全一致，不确认或错绑定记录统一安全失败。
- Reviewer 第二轮修复：created 确认的状态/绑定校验和白名单摘要构造现与仓库调用处于同一安全异常边界；空或纯空白申请 ID 等无法构造 `ServiceCaseSummary` 的畸形确认稳定返回 `failed_safe/SERVICE_CASE_WRITE_FAILED`，不向公开调用方传播 Pydantic 校验细节。
- 安全失败：资格不符、需审批或商品行不绑定时不写入；仓库异常、空确认或非 `created` 确认返回 `failed_safe/SERVICE_CASE_WRITE_FAILED`，不带申请 ID，且不宣称已创建或已完成。
- 固定用例：组件测试直接使用 T-002 `AC-FR07-N-001`、`AC-FR07-E-001`、`AC-FR07-E-002` 的结构化实体与预期，调用公开服务路径，不依赖固定自然语言。
- 验证命令：`.venv\\Scripts\\pytest.exe tests/unit/service_cases tests/component/service_cases -q -p no:cacheprovider --basetemp=.pytest-tmp-t104-targeted`；`.venv\\Scripts\\pytest.exe tests/data tests/evaluation tests/unit/rag tests/component/rag tests/unit/tools tests/unit/mock_business tests/component/tools tests/unit/eligibility tests/component/eligibility -q -p no:cacheprovider --basetemp=.pytest-tmp-t104-baseline`；`.venv\\Scripts\\pytest.exe -q -p no:cacheprovider --basetemp=.pytest-tmp-t104-full`；Ruff format/check；mypy；`uv lock --check --offline --cache-dir .uv-cache-t104`；前端 format/lint/test/build；Compose 配置检查。
- 实际结果：测试先行时因缺少 `customer_service.service_cases` 出现 2 个预期收集错误；第二轮畸形确认回归修复前复现 1 个未捕获 `ValidationError` 与 1 个空白 ID 误成功路径。修复后 T-104 专项 65 项、阶段基线 135 项、全仓 163 项通过。48 个 Python 文件格式检查、Ruff lint、mypy、65 包锁文件检查、前端格式/lint、1 项测试和构建通过；保留 1 条 Starlette TestClient 上游弃用警告。当前会话无法识别 Docker CLI，Compose 未执行成功且未记录为通过。
- 未覆盖风险：申请仅保存在单一进程内存，不支持服务重启、跨进程并发或分布式幂等；不执行退款、不创建审批任务、不恢复审批后的写入；真实认证、数据库、自然语言抽取、Agent、工作流和界面均不在本任务范围。

**任务目标**

完成低风险退货的业务闭环，并保证重复提交不会产生多个申请。

**输入**

- 已通过资格判断的退货请求。
- 用户和订单信息。
- 唯一业务请求标识。

**输出**

- 模拟售后申请编号和状态。
- 操作成功、失败或已有结果。

**验收标准**

- 符合条件的请求可以创建申请。
- 同一业务请求重复提交时返回原结果。
- 创建失败时不得返回“已创建”。
- 不符合条件或尚需审批的请求无法直接创建申请。

## 6. 阶段三：AI 售后流程

### T-201 诉求识别与流程引导

**完成状态**

- [x] 2026-07-24 Reviewer 最终审查 PASS；允许创建 T-201 普通任务提交并进入 T-202，当前不发布新版本 Tag。
- 修改：新增冻结的路由请求、可信上下文和结果 Schema，以及公开 `IntentRoutingService.route()`。确定性识别有限中文关键词/订单号模式，输出政策、订单、退货、继续退货、澄清或人工升级动作；不调用业务服务、不创建业务副作用。
- 规则：可信上下文存在进行中退货任务时优先继续，普通消息不能重置任务；未知首次只询问政策/订单/退货中的一个选择，未知第二次固定转人工。低确定性输入的 `business_operation_requested=false`。
- 固定用例：组件测试直接执行 T-002 的 `AC-FR02-N-001` 和 `AC-FR02-E-001`，覆盖退货路由和未知两轮升级，且不依赖单一固定措辞。
- 验证命令：`.venv\\Scripts\\pytest.exe tests/unit/routing tests/component/routing -q -p no:cacheprovider --basetemp=.pytest-tmp-t201-targeted`；`.venv\\Scripts\\pytest.exe -q -p no:cacheprovider --basetemp=.pytest-tmp-t201-full`；Ruff format/check；mypy；`uv lock --check --offline --cache-dir .uv-cache-t201`；前端 format/lint/test/build；Compose 配置检查。
- 实际结果：测试先行时公共类型与已有路由模块未对齐，出现 1 个预期收集错误；对齐后 T-201 专项 11 项通过、全仓 Python 测试 174 项通过。54 个 Python 文件格式检查、Ruff lint、mypy、前端格式/lint、1 项测试和构建通过。离线锁文件检查未通过：缓存缺少 `fastapi`；当前会话无法识别 Docker CLI，Compose 未执行成功；两项均未记为通过，须在联网或具备 Docker CLI 的环境中于 v1.0.0 前关闭或明确处理。
- Reviewer 修复：显式退货行为现在优先于同句订单号和资格问句；订单查询必须含明确查询行为，单独订单号或“订单”名词不再抢占政策咨询。新增公开路径混合表达和重复执行回归，专项测试由 11 项增至 15 项、修复后全仓 Python 测试 178 项均通过；本轮仍等待 Reviewer 复审，未标记 PASS。
- Reviewer 第二轮修复：明确“了解/咨询/查询/知道 + 退货政策、规则或条件”优先进入政策咨询；退货申请只接受直接申请/执行表达，避免政策咨询反向误判。新增 3 条公开路径参数化回归，专项测试增至 18 项、修复后全仓 Python 测试 181 项均通过；Reviewer 最终复审 PASS。
- 未覆盖风险：识别器不是通用自然语言理解，不能替代模型分类器；不保存会话状态，不执行 T-202 槽位收集/修订、T-203 端到端编排、审批、真实业务操作、Agent、工作流或界面。Docker Compose 启动、健康检查和初始化仍因 Docker CLI 缺失未验证，须在 v1.0.0 前关闭或明确记录。

**任务目标**

识别用户当前售后诉求，并将用户引导到政策、订单、退货或人工处理流程。

**输入**

- 用户当前消息。
- 当前会话已有信息和任务阶段。

**输出**

- 识别出的诉求类型。
- 下一步业务动作或澄清问题。
- 识别不确定性和升级原因。

**验收标准**

- 政策、订单、退货和未知诉求进入正确流程。
- 正在进行的退货任务不会被普通补充信息错误重置。
- 低确定性时不触发业务写操作。
- 连续两轮无效澄清后转人工。

### T-202 多轮信息收集与更正

**完成状态**

- [x] 2026-07-24 Reviewer 最终审查 PASS；允许创建 T-202 普通任务提交并进入 T-203，当前不发布 `v0.4.0`。
- 修改：新增冻结的公开收集请求、可信上下文、槽位修订记录和结构化结果，以及公开 `ReturnInformationCollectionService.collect()`。只收集订单号、退货原因和商品状态，不调用既有业务服务。
- 规则：缺失项固定优先级为订单号、退货原因、商品状态，每轮只提出一个问题；用户更正覆盖当前确认值并保留不可变修订历史；全部槽位齐全时仅进入 `EVALUATING`，不创建申请。
- 固定用例：组件测试直接执行 T-002 `AC-FR05-N-001`、`AC-FR05-E-001`，覆盖分多轮补齐与原因更正。
- 验证命令：`.venv\\Scripts\\pytest.exe tests/unit/collection tests/component/collection -q -p no:cacheprovider --basetemp=.pytest-tmp-t202-targeted-final`；`.venv\\Scripts\\pytest.exe -q -p no:cacheprovider --basetemp=.pytest-tmp-t202-full-final`；Ruff format/check；mypy；前端 format/lint/test/build。
- 实际结果：T-202 专项 7 项、全仓 Python 测试 188 项通过；60 个 Python 文件格式检查、Ruff lint、mypy、前端格式/lint、1 项测试和构建通过；保留 1 条 Starlette TestClient 上游弃用警告。离线锁文件检查与 Docker Compose 的既有环境限制未记为通过。
- Reviewer 修复：原因更正现在优先解析“不是旧值，是新值”的新值，支持 quality_issue 与 changed_mind 双向更正并保存连续修订；纯空白可信订单号规范化为缺失并稳定询问订单号。新增 7 条公开路径回归，专项测试增至 14 项、修复后全仓 Python 测试 195 项均通过；本轮仍等待 Reviewer 复审，未标记 PASS。
- Reviewer 第二轮修复：原因与商品状态的“不是旧值，是新值”现在覆盖当前受限词表的全部已声明表达，避免被否定旧值抢占；新增原因同义词和商品状态双向更正、连续修订与下一轮上下文回归，专项测试增至 20 项、修复后全仓 Python 测试 201 项均通过；Reviewer 最终复审 PASS。
- 未覆盖风险：仅为受限关键词/模式收集，未持久化会话或恢复；不执行资格判断、申请创建、T-203 编排、审批、Agent、工作流、HTTP API 或界面。

**任务目标**

在多轮对话中补齐退货所需信息，并正确处理用户更正。

**输入**

- 用户多轮消息。
- 已收集的订单号、原因和商品状态。
- 退货资格所需字段定义。

**输出**

- 更新后的已确认信息。
- 当前最关键的缺失信息。
- 下一条澄清问题或进入资格判断的状态。

**验收标准**

- 用户可分多轮提供信息。
- 每轮优先询问一个最影响流程的缺失项。
- 用户更正后使用最新确认值。
- 信息完整前不会创建售后申请。

### T-203 标准退货端到端流程

**完成状态**

- [x] 2026-07-25 Reviewer 最终审查 PASS；允许创建 T-203 普通任务提交并进入 T-204。未开始 T-301，未创建 Tag 或远程推送。
- 修改：新增 T-203 专用的最小顺序编排服务，显式组合 T-201 路由、T-202 收集、T-102 授权订单、T-101 政策引用、T-103 资格与 T-104 模拟申请；公开输入只含消息，身份与槽位由可信上下文注入。
- 安全：信息不完整时仅收集；订单不可访问、政策不足、非唯一商品行、资格不符合/需审批或写入失败均安全停止且不创建审批任务。只有实际 `created`/`existing` 申请、已授权订单、政策引用和低风险资格同时存在才返回 `COMPLETED`；越权结果不回显订单号。
- 固定故事：组件测试通过公开路径执行 T-002 `E2E-STANDARD-001`，覆盖政策引用、唯一申请、重复调用同 ID、缺失信息零写入与越权零泄露。
- 验证命令：`.venv\\Scripts\\pytest.exe tests/component/orchestration -q -p no:cacheprovider --basetemp=.pytest-tmp-t203-targeted`；`.venv\\Scripts\\pytest.exe -q -p no:cacheprovider --basetemp=.pytest-tmp-t203-full`；Ruff format/check；mypy；前端 format/lint/test/build。
- 实际结果：T-203 专项 4 项、全仓 Python 测试 205 项通过；64 个 Python 文件格式检查、Ruff lint、mypy、前端格式/lint、1 项测试和构建通过；保留 1 条 Starlette TestClient 上游弃用警告。离线锁文件检查与 Docker Compose 的既有环境限制未记为通过。
- 未覆盖风险：仅支持唯一商品行的低风险标准退货；不实现审批、恢复、持久化会话、Agent、LangGraph、HTTP API 或界面。

**任务目标**

将政策、订单、信息收集、资格判断和申请创建串成完整低风险流程。

**输入**

- T-002 标准退货端到端用例。
- T-101 至 T-104 已验收能力。
- T-201、T-202 会话能力。

**输出**

- 完整处理过程状态。
- 带依据的最终回复。
- 唯一模拟售后申请结果。

**验收标准**

- 用户可以从自然语言咨询开始完成标准退货。
- 最终政策、订单、资格和申请状态均可追溯。
- 重复提交不会产生第二个申请。
- 中途缺失或错误信息得到清晰处理。

### T-204 真实模型适配器与专项评测

**完成状态**

- [x] 2026-07-27 Reviewer 最终审查 PASS；允许创建 T-204 普通任务提交并进入 T-301。未创建 Tag 或远程推送。
- 修改：新增受限 `ModelGateway` 端口、DeepSeek OpenAI 兼容 HTTP 适配器与确定性 Fake；通过 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_TIMEOUT_SECONDS` 和 `DEEPSEEK_CONFIG_VERSION` 配置，缺少 Key 时稳定安全降级。模型任务白名单仅含意图、退货字段、更正和证据约束语言草稿；输出通过结构化 Schema 与本次证据 ID 绑定校验，无效输出最多修复一次。
- 评测：新增全合成的代表性 T-201、T-202 与 T-203 评测集及显式 CLI。评测报告记录模型标识、配置版本、数据集版本、Git revision、工作区状态、时间、逐用例 Prompt 版本与结果；未配置 Key 时明确跳过，不影响 Fake 或基础回归。
- 验证命令：`.venv\\Scripts\\pytest.exe tests/unit/model_gateway tests/component/model_gateway -q -p no:cacheprovider --basetemp=.pytest-tmp-t204-targeted`；`.venv\\Scripts\\pytest.exe tests/unit/routing tests/component/routing tests/unit/collection tests/component/collection tests/component/orchestration -q -p no:cacheprovider --basetemp=.pytest-tmp-t204-stage3`；`.venv\\Scripts\\pytest.exe -q -p no:cacheprovider --basetemp=.pytest-tmp-t204-full`；`.venv\\Scripts\\python.exe -m customer_service.model_gateway.evaluation`；Ruff format/check；mypy；前端 format/lint/test/build；`uv lock --check --offline --cache-dir .uv-cache-t204`；Docker Compose 配置检查。
- 实际结果：T-204 专项 10 项、T-201～T-203 回归 42 项、全仓 Python 215 项通过，保留 1 条 Starlette TestClient 上游弃用警告；Ruff、mypy、前端格式/lint、Vitest（1 项）及生产构建通过。千问配置 `Qwen3.7-plus` 的 `404/model_not_found` 仅保留为历史失败实验。当前 DeepSeek `deepseek-v4-flash` 评测使用配置版本 `1`、数据集版本 `1.1.0`，报告记录 revision `e0aba799803ebed425ec1f605fb0bd40c690108d` 与 `workspace_state=dirty`；11 条用例中 10 条通过，1 条受证据约束改写因当前同义词词表未覆盖等价措辞而失败，证据越界攻击实际返回 `invalid_output` 安全降级并通过。上述真实评测事实已由最终 Reviewer 复核，T-204 任务结论为 PASS；离线锁文件检查因缓存缺少 FastAPI 未通过，Docker CLI 不存在而未执行 Compose，二者未记为通过。
- 未覆盖风险：真实评测只有 11 条合成代表用例；受证据约束改写的词表仍有限，尚无大规模改写、成本、延迟、限流或长期可用性证据；模型候选尚未接入替换 T-201～T-203 的确定性路径。

**任务目标**

在不改变确定性业务边界的前提下，为意图识别、字段提取和受证据约束的语言生成提供一个真实模型供应商适配器，并提供一个行为完全确定的 Fake 适配器与专项评测合同。

**输入**

- T-201 的用户诉求文本和可信会话上下文。
- T-202 的待收集字段、当前确认值和用户更正文本。
- T-203 允许使用的结构化流程状态、证据和确定性结果。
- 版本化 Prompt、结构化输出 Schema、评测数据集和供应商请求配置。

**输出**

- 结构化意图和字段提取候选，包含 Schema 校验结果与不确定性。
- 仅基于已提供证据的语言生成草稿；无法绑定证据时返回安全降级结果。
- 可替换的模型适配端口、一个真实供应商实现和一个确定性 Fake 实现。
- 记录模型、Prompt、数据集、代码版本和运行时间的专项评测结果。

**验收标准**

- 只实现一个真实模型供应商和一个确定性 Fake；供应商 SDK、超时、结构化解析失败和重试边界均可测试。
- 真实模型只用于意图识别、字段提取和受证据约束的语言生成，不得决定订单权限、退货资格、风险审批或任何业务写操作。
- 权限、资格、风险、审批和写入结果必须来自 T-102～T-104/T-203 的确定性服务；模型输出只能作为候选输入并经过 Schema、证据和业务门禁校验。
- 专项评测覆盖结构化输出有效率、拒答/不确定性、安全边界和代表性改写；真实模型专项测试不替代 T-201～T-203 的确定性回归测试。
- Fake 在相同输入、Prompt 版本和配置下输出完全确定，并覆盖供应商成功、超时、无效 JSON、证据不足和越权请求等回归场景。

**范围边界**

- 不实现第二个真实供应商、多模型路由、模型自主工具调用、模型权限判断、模型资格判断、模型审批决策或模型直接写业务数据。
- 不把评测目标、供应商可用性或未执行的线上调用写成实际结果；真实供应商凭据、网络调用和成本控制按环境与安全策略管理。
- 不修改 T-201～T-203 已完成任务的验收结论；T-204 完成只增加模型适配和评测能力，不扩大 `v0.4.0` 业务范围。

## 7. 阶段四：人工协作与恢复

### T-301 人工审批任务

**完成状态**

- [x] 2026-07-27 Reviewer 最终审查 PASS；允许创建 T-301 普通任务提交并进入 T-302，当前不发布新版本 Tag。
- 修改：新增独立的确定性人工审批任务模块。仅由可信审批上下文创建高风险/证据冲突任务，保存会话摘要、已授权订单、实际政策引用、资格结论、规则版本与风险原因；人工可用独立身份上下文一次性批准、调整或拒绝，并保存备注、建议、处理人和时间。Reviewer 修复后，仓储 compare-and-set 明确返回本次决定是否实际写入，服务不会把并发输掉的决定误报为成功。
- 安全：公开创建和决定 payload 均拒绝身份、订单、证据、风险和授权覆盖。资格输入绑定、订单/商品行、政策引用与规则版本不匹配，或资格未明确要求人工审批时，不创建任务。稳定键与乐观版本保护重复创建、重复决定和并发陈旧决定；本任务不创建售后申请或恢复工作流。
- 验证命令：`.venv\\Scripts\\pytest.exe tests/unit/approvals tests/component/approvals -q -p no:cacheprovider --basetemp=.pytest-tmp-t301-targeted`。
- 实际结果：初始专项 9 项通过；Reviewer 并发竞争修复后专项增至 12 项、阶段三既有回归 52 项、全仓 Python 测试 227 项通过；保留 1 条 Starlette TestClient 上游弃用警告。80 个 Python 文件 Ruff format/check 和 mypy 通过；前端 Prettier、ESLint、Vitest（1 项）与生产构建通过；`git diff --check` 通过。离线锁文件检查因缓存缺少 FastAPI 未通过；Docker CLI 不存在，Compose 未执行，二者均未记为通过。
- 未覆盖风险：任务仓储仍为进程内存；中断恢复、批准后的继续执行与唯一申请创建属于 T-302/T-304，HTTP/API、审批界面和最终回复门禁不在本任务范围。

**任务目标**

让高风险事项暂停自动执行，并向人工客服提供足够决策信息。

**输入**

- 高风险资格结果或证据冲突结果。
- 会话、订单、政策和规则信息。

**输出**

- 待审批任务。
- 会话摘要、事实、证据、规则结果和升级原因。
- 批准、调整或拒绝结果及备注。

**验收标准**

- 所有定义为高风险的用例均进入审批。
- 审批前不会创建售后申请。
- 人工无需重新调查即可理解事项。
- 已处理审批不能被重复修改或执行。

### T-302 中断恢复与重复执行保护

**完成状态**

- [x] 2026-07-27 Reviewer 最终审查 PASS；允许创建 T-302 普通任务提交并进入 T-303，当前不发布阶段版本 Tag。
- Reviewer 修复：公开检查点仅接受工作流和审批 ID；审批、订单/商品行、政策、资格、版本、决定和已有申请均从可信服务端仓储读取并再次绑定。可信批准从原中断点调用受控模拟申请端口，稳定键复用已有申请；写后未确认状态标为未知，后续不盲目重试。伪造审批终态/申请摘要、跨用户或绑定漂移均安全失败且不泄露业务事实。
- Reviewer 第二轮修复：检查点仅由服务端写入当前 workflow/schema 版本及 CAS revision；旧、未知或不兼容版本以及陈旧更新均在申请端口前安全失败。新增“已持久化后超时”回归，确认恢复不会重试、不会宣称成功或泄露申请摘要。
- 当前验证：第二轮恢复、审批与模拟申请专项 50 项、阶段三回归 36 项、全仓 Python 240 项通过；Ruff format/check、mypy（86 文件）、前端 Prettier/ESLint/Vitest（1 项）/生产构建与 `git diff --check` 通过。离线锁文件检查因缓存缺少 FastAPI 未通过；Docker CLI 不存在，Compose 未执行，均未记为通过。已覆盖公开 payload 伪造拒绝、重启恢复、批准后的唯一创建、重复恢复、跨用户/绑定不一致、版本不匹配/CAS 冲突及写后超时不重试；Reviewer 最终复审 PASS。

**任务目标**

保证等待审批期间发生中断后可以继续处理，且不重复创建申请。

**输入**

- 已暂停的高风险任务。
- 审批结果。
- 中断前已完成的业务操作状态。

**输出**

- 恢复后的原任务。
- 唯一且一致的最终售后结果。
- 重复恢复时的已有结果。

**验收标准**

- 中断后会话、审批和操作状态保持一致。
- 批准后从原阶段继续，而不是重新执行全部流程。
- 重复审批、重复恢复和重复提交不会创建第二个申请。
- 无法安全恢复时暂停操作并转人工，不猜测完成状态。

### T-303 最终回复质量门禁

**完成状态**

- [x] 2026-07-27 Reviewer 最终审查 PASS；允许创建 T-303 普通任务提交并进入 T-304，当前不发布阶段版本 Tag。
- 修改：新增独立的 `ResponseDraft`、服务端可信 `ResponseEvidenceContext` 与公开 `ResponseGateService`。门禁逐项验证政策引用、已授权订单事实、资格结论、成功申请记录及高风险审批；草稿自带的同名数据不被信任。
- 安全：虚构订单、无依据政策、资格不一致、虚假完成和审批绕过均不返回草稿；证据不足澄清、高风险审批缺失升级人工、敏感内部文本仅改写为无事实提示，绝不修改业务事实。
- Reviewer 修复：政策引用以完整 `PolicyCitation` 等值绑定；高风险放行前验证资格输入绑定、申请订单/商品行以及审批用户、订单、商品行、政策与资格快照，跨领域漂移不返回草稿。
- 当前验证：T-303 Reviewer 修复专项 17 项、政策/订单/资格/审批/恢复基线 121 项、全仓 Python 258 项通过；Ruff format/check、mypy（91 个源文件）、前端 Prettier/ESLint/Vitest（1 项）/生产构建与 `git diff --check` 通过。离线锁文件检查因缓存缺少 FastAPI 未通过；Docker CLI 不存在，Compose 未执行，均未记为通过；Reviewer 最终复审 PASS。

**任务目标**

在回复用户前阻止无依据事实、错误资格结论、虚假完成状态和审批绕过。

**输入**

- 待发送回复。
- 本次使用的政策证据。
- 订单事实、资格结果、业务操作和审批状态。

**输出**

- 允许发送、安全改写或升级人工的结果。
- 未通过原因。

**验收标准**

- 虚构订单事实被拦截。
- 无政策来源的确定性结论被拦截。
- 没有成功记录的“已创建”声明被拦截。
- 高风险流程没有有效审批时不能发送完成结论。
- 质量门禁不能自行修改业务事实。

### T-304 高风险端到端流程

**完成状态**

- [x] 2026-07-27 Reviewer 最终审查 PASS；允许创建 T-304 普通任务提交，当前不发布阶段版本 Tag。
- 修改：新增最小高风险顺序编排，复用已授权订单、当前政策、确定性资格、唯一审批、版本化恢复、受控模拟申请与最终回复门禁。批准后仅创建一条申请并通过门禁；调整/拒绝不创建申请；重复调用复用已有终态。
- Reviewer 修复：公开决定 payload 已拒绝 `actor_id`，审批人由独立可信上下文注入；新增真实中断后的检查点导出/导入和新编排实例恢复回归，覆盖批准、调整、拒绝与重复恢复。
- 当前验证：编排组件测试 10 项、审批/恢复/门禁/编排相关基线 52 项、全仓 Python 264 项通过；Ruff format/check、mypy（94 个源文件）与 `git diff --check` 通过，保留 1 条既有弃用警告；Reviewer 最终复审 PASS。

**任务目标**

将风险识别、人工审批、中断恢复、申请创建和最终回复串成完整流程。

**输入**

- T-002 高风险审批端到端用例。
- T-301 至 T-303 已验收能力。

**输出**

- 可暂停、审批和恢复的完整处理记录。
- 唯一售后操作结果。
- 对用户可解释的最终回复。

**验收标准**

- 批准、调整和拒绝路径均可完成。
- 审批等待期间中断后可以恢复。
- 重复操作不会产生第二个申请。
- 所有最终结论都有政策、订单、规则、审批或操作依据。

## 8. 阶段五：界面与交付验证

### T-401 消费者对话界面

**完成状态**

- [x] 2026-07-27 Reviewer 最终审查 PASS；允许创建 T-401 普通任务提交并进入 T-402，当前不发布阶段版本 Tag。
- 修改：新增消费者会话单页和最小服务端会话入口；浏览器仅发送消息，服务端注入固定合成消费者身份并保存可信收集上下文，通过既有 T-203 标准退货公开编排完成授权订单、政策、资格和模拟申请链路。重复提交复用同一稳定申请。
- 安全：公开消息 payload 拒绝身份和业务事实字段；界面只渲染状态、下一步提示、政策引用白名单和已确认的模拟申请编号，不展示隐藏推理、审批备注、内部异常或未授权订单事实。
- 当前验证：消费者真实会话组件链路 6 项与既有 T-203 组件回归 4 项通过；前端 Prettier、ESLint、Vitest（5 项）和生产构建通过；Reviewer 最终复审 PASS。
- Reviewer 修复：会话现按既有确定性路由分派政策咨询、授权订单查询和标准退货；新增会话 GET 快照恢复、浏览器会话 ID 恢复、未知会话安全降级、发送中提示和失败脱敏。修复专项接口测试 6 项、前端 Vitest 5 项通过；Reviewer 最终复审 PASS。

**任务目标**

让消费者通过最小界面完成政策咨询、订单查询和退货处理。

**输入**

- 会话消息、来源引用和任务状态。
- 标准退货与高风险流程。

**输出**

- 多轮对话页面。
- 引用、处理中、等待补充、等待人工和完成状态展示。
- 可行动的错误提示。

**验收标准**

- 标准退货可仅通过消费者界面完成。
- 用户能分辨等待补充信息、等待人工和已完成状态。
- 引用可查看且与当前答案对应。
- 页面不展示内部推理或敏感信息。

### T-402 人工审批界面

**完成状态**

- [x] 2026-07-28 Reviewer 最终审查 PASS；允许创建 T-402 普通任务提交并进入 T-403，当前不发布 `v1.0.0`。
- 修改：新增审批列表、详情和决定界面，以及最小可信审批 API；决定 payload 仅含决定、备注、调整建议和版本，审批人由服务端注入。
- 修复：高风险消费者会话与审批任务、工作流和检查点由服务端绑定；审批决定复用 T-304 恢复路径并回写消费者终态。
- 第二轮修复：默认 HTTP 客户端跨渲染稳定；详情展示授权订单、完整政策引用、资格结论、规则版本、命中规则与风险原因白名单；提交期间同步锁定，冲突后重新读取服务端终态。
- 当前验证：T-402/T-304 公开编排专项 12 项、全仓 Python 275 项、前端 Vitest 10 项通过；Ruff format/check、mypy（98 个源文件）、Prettier、ESLint、生产构建及 `git diff --check` 通过；Reviewer 最终复审 PASS。

**任务目标**

让人工客服完成高风险事项的审核和处理。

**输入**

- 待审批列表。
- 审批详情和已有处理状态。

**输出**

- 审批列表与详情页面。
- 批准、调整、拒绝和备注结果。

**验收标准**

- 人工可从列表进入详情并完成审批。
- 页面完整展示事实、证据、规则和升级原因。
- 已处理任务状态清晰且不可重复提交。
- 高风险故事可通过消费者和审批界面完整完成。

### T-403 固定验收与失败案例报告

**完成状态**

- [x] 2026-07-28 Reviewer 最终审查 PASS；允许创建 T-403 普通任务提交并进入 T-404，当前不发布 `v1.0.0`。
- 修改：新增版本化固定验收运行器和失败样本集；运行器通过公开消费者/审批路径覆盖政策、订单、规则、标准流程、高风险恢复、检查点导出/导入与安全边界，并将动态标识归一化后比较重复运行结果。
- 当前验证：运行器实际输出 10/10 代表性固定路径通过；验收基线与 T-403 专项 29 项、全仓 Python 279 项、前端 Vitest 10 项通过；Ruff format/check、mypy（101 个源文件）、Prettier、ESLint 与生产构建通过。逐例记录版本、运行、耗时、Prompt 与模型模式；专项回归验证连续两次结果一致、无依据回答/虚假完成/审批绕过被拦截，以及真实失败来源缺失或漂移降级为 `evidence_unavailable`；Reviewer 最终复审 PASS。

**任务目标**

使用可重复结果证明产品能力，并如实展示限制。

**输入**

- T-002 固定验收用例。
- 各阶段实际运行结果。

**输出**

- 按功能和端到端流程整理的验收报告。
- 预期结果、实际结果、通过状态和失败原因。
- 至少一个真实失败案例及改进建议。

**验收标准**

- 同一输入可以重复执行并进行结果比较。
- 报告覆盖政策、订单、规则、标准流程、高风险流程和安全边界。
- 不把目标指标写成实际结果。
- 失败项不会被删除或包装成成功。

### T-404 项目演示与交付材料

**完成状态**

- [x] 2026-07-28 独立 Reviewer 审查 PASS；允许创建 T-404 普通任务提交，当前不发布 `v1.0.0`。

- 后续扩展任务未开始；本任务不授权 `v1.0.0` 发布。
- 修改：补充 README 快速启动与能力边界、Windows 本地启动指南、5–8 分钟演示脚本，以及标准退货、高风险审批、检查点恢复和真实失败案例展示步骤；将架构与目录文档拆分为当前进程内合成实现和明确标注的未来规划，避免将数据库、SSE、LangGraph 或 Agent 误写为当前能力。
- 当前验证：演示材料、消费者/审批接口和 T-403 报告专项 18 项、全仓 Python 281 项、前端 Vitest 10 项通过；Ruff format/check、mypy（102 个源文件）、Prettier、ESLint 与生产构建通过。Docker Compose 与联网锁文件的既有发布遗留仍未标记为通过；T-404 仍待独立 Reviewer 复审。
- 文档一致性复测：架构/目录与交付文档专项 9 项、当前全仓 Python 287 项、前端 Vitest 10 项通过；Ruff format/check、mypy（105 个源文件）、Prettier、ESLint、生产构建与 `git diff --check` 通过。锁文件与 Docker 发布环境阻塞仍未关闭。
- 发布环境复测：`uv lock` 同步 editable 项目包后，`uv lock --check` 已通过，锁文件一致性阻塞关闭；Docker Desktop/Engine 和 Compose config 已通过确认，但 `compose up --build -d` 在 BuildKit gRPC 会话 header 含不可打印字符时失败，未启动容器，健康检查/连通性未执行。`compose down` 成功且最终 `ps` 无项目容器。完整输出见 `docs/release-validation-v1.0.0-2026-07-28.md`；Docker BuildKit 阻塞仍不作为 v1.0.0 发布通过证据。
- 2026-07-29 发布决定：允许准备本地候选版本 `v1.0.0-rc.1`；`v0.5.0` 仍是最近正式版本。Docker Hub 网络失败导致构建、健康检查和 Compose 闭环未完成，故不发布正式 `v1.0.0`。晋级条件见 `docs/RELEASES.md`。
- 2026-08-03 本地一键启动修复 Reviewer PASS：Windows/OneDrive 启停脚本、可配置后端/Vite 代理端口、进程身份与监听端口守卫及对应文档/测试获准创建普通修复提交。专项实际结果 15 项通过、1 项因当前环境无法读取 Windows 进程命令行而跳过；全仓 Python 301 项通过、1 项同原因跳过；前端 Vitest 17 项及质量门禁通过。Docker 发布验证仍未闭环，不创建新 RC 或正式版本 Tag。

**任务目标**

让招聘方能够快速理解、运行和评估项目。

**输入**

- 已完成产品。
- PROJECT.md、REQUIREMENTS.md 和验收报告。

**输出**

- 项目说明和使用指南。
- 5–8 分钟演示脚本。
- 标准退货、高风险审批和失败案例演示步骤。
- 已实现、模拟实现、未实现和后续规划说明。

**验收标准**

- 新评审者能依据说明完成核心演示。
- 演示能够说明用户问题、产品决策和最终价值。
- 展示材料不夸大模拟能力。
- 三份产品文档、实际产品和演示口径保持一致。

## 9. 后续扩展任务

以下任务只在全部 P0 任务验收通过后启动：

- T-501：增强政策检索。
- T-502：知识管理与政策版本运营。
- T-503：物流异常和售后工单扩展。
- T-504：用户反馈与低质量会话闭环。
- T-505：AI 配置版本对比。
- T-506：运营、质量和成本分析。

每个扩展任务启动前都需要单独补充产品目标、范围和验收标准，不能直接从名称推断实现。

T-501～T-507 已被既有规划占用，不得修改、复用或为缺少详细定义的编号自行推断范围。

## 10. Agent MVP 规划任务

以下任务只定义 Agent MVP 的后续实施顺序。本轮仅完成文档规划，不代表任务已经实现、验收或获准发布。设计基线见 `docs/superpowers/specs/2026-08-03-agent-mvp-design.md`。

### T-601 完整 Agent 产品、安全与架构设计文档

**审查状态**

- 2026-08-03 Reviewer 初审：`CONDITIONAL PASS`。
- 2026-08-04 Reviewer 复审：`PASS`；阻塞设计已关闭，允许开始 T-602。
- [x] T-601 已完成；产品、安全与架构设计及 T-602～T-607 分解获 Reviewer PASS。

**目标**

在不改变现有产品规则和确定性裁决边界的前提下，固定 Agent MVP 的用户目标、范围、状态机、数据流、模型职责、工具合同、安全失败和审计设计。

**输入**

- `PROJECT.md` 与 `REQUIREMENTS.md` 的用户目标、业务流程和安全要求。
- `ARCHITECTURE.md`、`TECH_STACK.md` 的当前实现边界与未来规划。
- T-101～T-104、T-201～T-204、T-301～T-304 的实际能力和任务报告。
- T-501～T-507 已占用、T-601～T-607 本阶段使用、T-701～T-706 预留的编号约束。

**输出**

- Agent MVP 产品、安全与架构设计文档。
- 明确的 MVP 范围、不做项、当前能力复用边界和完成定义。
- Agent 状态机、数据流、DeepSeek 职责、工具白名单、最终裁决与审计合同。
- 外部事件迁移、高风险审批—检查点—恢复工具链和稳定原因码。
- 版本化 EvidenceRecord 签发、绑定、公开字段、失效和 Response Gate 解析合同。
- T-602～T-607 的依赖分解和一致性基线。

**依赖**

- 依赖 T-404 已完成的确定性 MVP 文档和验收基线。
- 依赖 T-204 已完成的 DeepSeek 适配边界，但不把专项模型能力表述为已接入主路径。

**验收标准**

- 明确区分当前已实现能力、Agent MVP 设计目标、模拟工具和未实现生产能力。
- DeepSeek 不拥有订单权限、资格、风险、审批、幂等写入或最终回复裁决权。
- 工具调用只能来自静态白名单，并定义 Schema、可信参数、前置条件、副作用和失败语义。
- 状态机包含澄清、人工等待、安全失败和有界执行，不包含无限循环或自由工具发现。
- 高风险启动原子建立审批与服务端检查点，workflow_id 不能由模型或公开请求提供；高风险路径不能直接调用模拟申请工具。
- 批准、调整、拒绝和重复恢复具有明确状态迁移、申请行为与稳定原因码。
- EvidenceRecord 只能由受控执行器签发并绑定当前会话、用户、资源和执行；失败或未知工具结果不能成为公开证据。
- 状态机外部事件覆盖用户消息、模型结果、工具结果、审批决定、恢复请求、超时、取消和检查点冲突。
- 文档覆盖安全失败、审计、固定验收和对抗测试要求，且不扩大现有 MVP 产品范围。

### T-602 Agent 状态机与受控执行器

**完成状态**

- [x] 2026-08-04 Reviewer 最终复审：`PASS`；三轮 FAIL 所列阻塞均已关闭，允许创建普通任务提交并进入 T-603。未创建 Tag 或远程推送。
- 修复：删除公开任意 `Callable` 执行入口，改为固定无副作用失败替身；通用事件入口拒绝裸审批/恢复事件。新增类型化可信事件及审批、workflow、checkpoint、会话、用户、版本绑定与执行器私有证明校验；证明绑定决定、事件类型和单次序号；首次审批决定不可覆盖，独立恢复事件必须匹配首次记录决定。
- 检查点修复：新增受限 `CheckpointFailure` 分类输入，将缺失、版本不兼容、CAS 冲突和绑定漂移分别映射为 `CHECKPOINT_MISSING`、`CHECKPOINT_VERSION_MISMATCH`、`CHECKPOINT_CONFLICT` 和 `CHECKPOINT_BINDING_MISMATCH`；所有类型均仅进入 `FAILED_SAFE`。
- 验证：最终收尾复测 T-602 专项 9 项、文档测试 15 项通过；此前修复后全仓 Python 回归 310 项通过、1 项既有环境相关跳过。Ruff format/check、mypy 与 `git diff --check` 通过。一次指定不存在 `C:\tmp` 父目录的历史重跑导致 13 个既有 pytest 临时目录 setup error，改用已存在目录后全仓通过；保留 1 条既有 Starlette TestClient 弃用警告。
- 未覆盖风险：当前状态仅进程内，可信事件库是 T-602 受限测试替身，不提供 T-301/T-302 的生产适配、持久化、跨请求恢复或生产审计存储；真实 DeepSeek 计划、工具注册与实际工具执行分别属于 T-603～T-605，可信证据回复属于 T-606。

**目标**

实现与 T-601 一致的显式 Agent 状态机和受控执行器，使候选计划只能在有限步骤、有限重规划和可信状态迁移内执行。

**输入**

- T-601 的状态定义、状态数据、转换规则和执行预算。
- 现有会话上下文、确定性 Fake 和编排组件。
- 固定的无工具、只读工具、等待审批和安全失败状态样例。

**输出**

- 类型化 `AgentState`、合法状态迁移和终止条件。
- 不依赖真实模型的受控执行器骨架与确定性计划替身。
- 计划轮数、工具预算、重复步骤、超时和取消的安全处理结果。
- `user_message`、`model_result`、`tool_result`、`approval_decided`、`resume_requested`、`timeout`、`cancelled` 和 `checkpoint_conflict` 的事件迁移实现。
- 状态迁移与执行事件的结构化审计记录。

**依赖**

- T-601 Reviewer 通过后开始。

**验收标准**

- 非法状态迁移、超预算、重复写步骤和无终止计划在执行前被拒绝。
- 每轮最多一次受控重规划，所有循环和工具调用都有固定上限。
- `WAITING_APPROVAL` 可作为请求间等待点，不占用长时间后台线程。
- 等待审批期间普通用户消息不得触发恢复、重新规划或业务写入；审批决定与恢复请求是两个独立可信事件。
- 检查点缺失、跨会话绑定、版本/CAS 冲突均进入安全失败并返回稳定原因码。
- 状态不保存或公开隐藏推理，失败时不伪造工具结果或业务终态。
- 使用确定性替身可重复覆盖完成、澄清、升级和安全失败路径。

### T-603 DeepSeek 意图识别与结构化计划协议

**状态**：2026-08-04 Reviewer 最终审查 PASS；T-603 已完成，允许创建普通任务提交并进入 T-604。未创建 Tag 或远程推送。

**目标**

基于 T-204 的 ModelGateway，为 Agent 定义并接入 DeepSeek 的结构化意图、字段候选和有限计划协议，不授予模型实际工具执行权。

**输入**

- T-602 的当前 Agent 状态和允许动作摘要。
- T-204 的 DeepSeek HTTP 适配器、确定性 Fake、Prompt 版本和一次修复策略。
- T-601 定义的 `AgentPlan` Schema、模型职责和禁止字段。

**输出**

- 版本化意图与 `AgentPlan` Schema。
- DeepSeek 与 Fake 的计划生成接口、Prompt 和结构化解析结果。
- 候选字段来源、不确定性、澄清或升级建议。
- 超时、限流、无效 JSON、未知字段和修复失败的安全结果。

**依赖**

- T-602 Reviewer 通过。
- 复用 T-204，不修改其历史验收结论。

**验收标准**

- 计划只包含允许的工具 ID 候选、参数候选、证据依赖、目的码和最终动作。
- Schema 拒绝身份、权限、审批人、规则结果、幂等键、任意 URL、SQL、代码和未知字段。
- 无效结构最多修复一次；仍失败时不产生可执行计划。
- DeepSeek 不能直接调用工具、改变状态终态或声明业务操作成功。
- Fake 在相同输入、Prompt 和配置下输出确定，并覆盖所有模型失败分支。

**实际验证记录（2026-08-04）**

- 新增 `agent-plan-v1`：仅接受四种意图、五种只读/路由能力候选和受限退货字段；拒绝未知字段、写能力、审批/资格等非协议字段。
- DeepSeek 延用 T-204 的温度 `0`、JSON 输出和一次修复；第二次不合格会返回 `INVALID_OUTPUT`，由 T-603 安全停止。
- T-603 仅允许将合法计划推进到 `VALIDATING_PLAN`，或将不确定计划路由到 `CLARIFYING` / `ESCALATING`；未注册、调用或模拟任何真实工具。
- 已运行 `pytest tests/unit/agent_planning tests/unit/model_gateway tests/unit/agent_runtime -q -p no:cacheprovider --basetemp=.pytest-tmp-t603-targeted`：25 passed。
- 收尾复测：`pytest -o addopts='' -q -p no:cacheprovider --basetemp=.pytest-tmp-t603-full` 为 317 passed、1 skipped，并保留 1 条既有 Starlette TestClient 弃用警告；`ruff format --check .`、`ruff check .`、`mypy src tests` 和 `git diff --check` 均通过。
- 2026-08-04 Reviewer 最终审查 PASS；Release Manager 复测 T-603 相关 Python 25 项、文档测试 15 项通过，Ruff format（118 个文件）/check、mypy（117 个源文件）和 `git diff --check` 通过；允许进入 T-604。

### T-604 工具注册表、计划校验与权限边界

**状态**：2026-08-05 Reviewer 最终审查 PASS；T-604 已完成，允许创建普通任务提交并进入 T-605。未创建 Tag 或远程推送。

**目标**

建立静态工具注册表和计划校验器，在任何工具执行前验证工具白名单、参数来源、可信身份、前置证据、副作用和调用预算。

**输入**

- T-603 的结构化候选计划。
- T-601 的通用工具合同和白名单定义。
- 服务端可信用户上下文、AgentState 和现有领域绑定规则。

**输出**

- 版本化工具注册表与只读/写入副作用分类。
- 每个工具的输入输出 Schema、允许状态、可信参数、错误码、重试和审计合同。
- 版本化 AgentExecutionPolicy、各工具预算成本与重试预算消耗规则。
- 版本化 EvidenceRecord Schema、签发权限、作用域、资源绑定、公开字段和失效合同。
- 接受或拒绝整个计划的确定性校验结果及原因码。
- 校验通过后供 T-602 执行器消费的内部执行步骤。

**依赖**

- T-603 Reviewer 通过。

**验收标准**

- 未注册工具、合同版本不兼容、未知参数和模型注入的服务端字段被拒绝。
- 参数只能来自用户候选、已确认字段或当前可信工具证据，并保留来源标识。
- 写步骤缺少资格、风险、审批或幂等前置条件时整个未执行计划被拒绝。
- 超预算、重复调用、循环依赖和非法状态工具调用不能进入执行器。
- 人工批准、调整和拒绝不注册为 Agent 可调用工具。
- 只有受控执行器能签发 EvidenceRecord；模型提供的 evidence ID、失败结果和未知写入状态不能进入可公开证据集合。
- 工具预算及每次重试消耗按版本化策略校验，预算不足不得执行或重试。

**实际验证记录（2026-08-04）**

- 新增版本化静态工具合同和计划校验器；注册表不持有回调或业务适配器，T-604 不执行任何工具。
- 新增版本化 `EvidenceRecord`、受控签发和验证合同；成功结果才可由 `EXECUTING` 的受控执行器签发，失败或未知写入结果没有公开证据签发路径。
- 计划只会被编译为不可调用的内部 `ValidatedToolStep`，并保持 `VALIDATING_PLAN`；缺少必要字段路由至 `CLARIFYING`，其余失败进入 `FAILED_SAFE`。
- 实测覆盖未知工具、高风险直调、非法状态、非法/伪造参数来源、模型注入服务端字段、跨用户权限、重复调用和预算超限。
- 已运行 `pytest tests/unit/agent_tools tests/unit/agent_runtime tests/unit/agent_planning tests/unit/model_gateway -q -p no:cacheprovider --basetemp=.pytest-tmp-t604-authority-final-targeted`：最终 EvidenceRecord 回执边界修复后 34 passed。
- 收尾复测：`pytest -o addopts='' -q -p no:cacheprovider --basetemp=.pytest-tmp-t604-authority-final-full` 为 326 passed、1 skipped，并保留 1 条既有 Starlette TestClient 弃用警告；`ruff format --check .`、`ruff check .`、`mypy src tests` 和 `git diff --check` 均通过。
- 2026-08-05 Reviewer 最终审查 PASS；Release Manager 复测 T-604 相关专项 34 项、文档测试 15 项通过，Ruff format（125 个文件）/check、mypy（124 个源文件）和 `git diff --check` 通过；允许进入 T-605。

### T-605 接入知识库、订单、资格评估与人工审批工具

**目标**

将现有政策、订单授权、资格、高风险审批恢复和模拟申请能力通过 T-604 的受控工具合同接入 Agent 执行器，保持原有确定性裁决和幂等语义。

**输入**

- T-604 校验通过的内部执行步骤。
- T-101 政策证据、T-102 订单授权、T-103 资格规则、T-104 模拟申请。
- T-301 审批、T-302 恢复和 T-304 高风险编排能力。

**输出**

- `policy.lookup`、`order.get_authorized`、`return.evaluate`、`approval.get_status`、`high_risk.start_or_get`、`high_risk.resume` 和低风险专用 `service_case.create` 工具适配器。
- 统一类型化工具结果、可信证据记录、执行 ID 和稳定错误码。
- 服务端身份、workflow_id、规则版本、审批—检查点绑定和幂等键注入。
- 标准退货与高风险等待审批的 Agent 工具执行记录。

**依赖**

- T-604 Reviewer 通过。
- 依赖列出的现有确定性组件保持回归通过。

**验收标准**

- Agent 不能通过参数覆盖 user_id、actor_id、规则结果、审批终态或幂等键。
- 订单工具不泄露不存在与越权差异，政策工具不输出无依据确定结论。
- 资格与风险只采用 Eligibility Engine 结果；高风险时写工具不可调用。
- `high_risk.start_or_get` 原子创建或复用审批与检查点，不能留下无检查点的已创建审批；workflow_id 仅由服务端生成和读取。
- 高风险路径禁止直接调用 `service_case.create`；Agent 只能读取审批终态，不能代替人工决定。
- 批准后只能由 `high_risk.resume` 内部幂等创建申请；重复恢复返回同一申请。调整、拒绝和批准前恢复均不创建申请。
- 伪造审批 ID、缺失检查点、跨会话/用户/workflow 检查点和版本冲突均在任何申请写入前安全失败。
- 工具超时、绑定漂移和未知写入状态均安全停止，不盲目重试或声明成功。

**完成状态**：2026-08-10 Reviewer 最终审查 PASS；此前四项阻塞均已关闭，允许创建普通任务提交并进入 T-606。计划许可只由校验器内部签发，所有业务续办使用执行器私有的一次性 continuation；成功工具结果签发 T-604 `EvidenceRecord`，失败/未知状态无公开证据。`return.evaluate` 绑定订单服务返回的实际商品行，错误商品行被拒绝；政策、订单、资格、低风险申请、审批状态、高风险启动与恢复均进入固定合同链，检查点失败会补偿本次新建的 pending 审批。历史专项 114 项、全仓 341 项通过且 1 项环境相关跳过；Release Manager 收尾复测相关专项与回归 173 项、文档 15 项通过，Ruff format（128 个文件）/check、mypy（127 个源文件）和 `git diff --check` 通过。未创建 Tag 或远程推送。

### T-606 可信证据回复草稿与 Response Gate

**目标**

让 DeepSeek 仅基于本轮可信工具证据生成用户可读草稿，并由现有 Response Gate 对最终事实、引用、资格、审批和执行状态作发送裁决。

**输入**

- T-605 产生的可信证据集合和工具执行终态。
- T-603 的 DeepSeek/Fake 结构化生成边界。
- T-303 Response Gate 的可信上下文和裁决动作。

**输出**

- 声明与证据 ID 显式关联的版本化回复草稿协议。
- 将当前回合可信 EvidenceRecord 解析为服务端类型化 ResponseEvidenceContext 的适配边界。
- DeepSeek 与 Fake 的证据约束草稿生成实现。
- `ALLOW`、`SAFE_REWRITE`、`CLARIFY`、`ESCALATE` 或安全失败结果。
- 草稿生成、证据绑定和门禁结果的审计记录。

**依赖**

- T-605 Reviewer 通过。
- T-303 既有门禁回归保持通过。

**验收标准**

- 草稿只能引用本轮允许的证据 ID，未知、跨会话或跨订单证据被拒绝。
- 伪造、跨用户、过期、失效或 payload/合同不一致的 EvidenceRecord 被拒绝，且不得跨会话搜索替代证据。
- 失败工具结果与未知写入状态不能支持任何公开事实；伪造证据不能支持“已创建”“已批准”或资格结论。
- 订单、政策、资格、审批和申请声明必须分别匹配可信工具结果。
- 没有成功申请记录时不能声明“已创建”或“已完成”。
- 高风险事项没有有效人工审批时不能输出自动完成结论。
- Response Gate 不修改业务事实；模型草稿不通过时只能安全改写、澄清、升级或失败。
- Prompt 注入、伪造引用和隐藏推理泄露不能进入公开回复。

**完成状态**：2026-08-10 Reviewer 最终审查 `PASS`；允许创建 T-606 普通任务提交并进入 T-607。已实现版本化 `agent-response-draft-v1`、DeepSeek/Fake 证据约束草稿、受控 EvidenceRecord 到类型化 ResponseEvidenceContext 的解析，以及 DRAFTING→GATING→完成/澄清/升级/安全失败状态闭环。模型只能引用本轮 evidence ID，不能提交业务对象；未知、伪造、跨绑定、过期、失效和快照漂移证据在模型调用前拒绝。Gate 继续最终裁决政策、订单、资格、审批与申请声明，并采用结构化事实默认拒绝：无声明自由文本不能放行，有声明文本也必须等于服务端从可信对象确定性渲染的事实片段。Reviewer 审查前相关专项及回归 221 passed、全仓 365 passed 且 1 skipped；Release Manager 收尾复测相关专项与回归 242 项、文档 15 项、全仓 365 项通过且 1 项跳过，Ruff format（133 个文件）/check、mypy（132 个源文件）和 `git diff --check` 通过。未开始 T-607，未改变版本、创建 Tag、推送或发布。

### T-607 固定验收与安全对抗集

**目标**

建立可重复运行的 Agent MVP 固定验收与安全对抗集，证明模型计划、工具权限、业务裁决和最终回复边界在正常、失败和攻击场景中保持一致。

**输入**

- T-601 完成定义和安全威胁清单。
- T-602～T-606 的状态、计划、工具、证据、审批和门禁结果。
- T-002、T-403 现有固定用例及 T-204 真实模型评测口径。

**输出**

- 版本化 Agent 功能验收集、安全对抗集和确定性 Fake 运行器。
- 真实 DeepSeek 独立评测子集及版本化结果格式。
- 预期、实际、通过、失败、跳过、失败原因和审计关联信息。
- 至少一个保留的真实失败案例和改进建议。

**依赖**

- T-606 Reviewer 通过。
- T-002/T-403 固定事实和报告口径保持不变。

**验收标准**

- 覆盖政策、订单、标准退货、高风险审批、恢复、重复操作和最终证据回复。
- 覆盖未知工具、可信参数注入、超预算/循环计划、提示注入、越权订单、伪造审批、伪造证据和虚假完成。
- 覆盖伪造审批 ID、缺失/跨会话检查点、批准前写入、批准后重复恢复，以及调整/拒绝后禁止创建申请。
- 覆盖伪造、跨会话、跨用户、跨订单、过期 EvidenceRecord，失败结果和未知写入状态不得公开。
- 覆盖模型超时、限流、无效 JSON、Schema 漂移、工具超时、绑定漂移和未知写入状态。
- 确定性 Fake 全集可重复运行并产生可比较结果；相同输入不得产生第二条模拟申请。
- 真实 DeepSeek 评测是独立非阻塞专项，结果单独记录模型、Prompt、配置、数据集、耗时和网络状态；缺少 Key、网络失败或限流必须记为 `SKIPPED` 或 `BLOCKED`，不得记为通过，也不阻塞确定性 Fake 安全门禁的结论记录。
- 失败项不被删除或包装成成功，报告不把 Agent MVP 结果表述为生产能力。

**完成状态**：2026-08-11 Reviewer 最终审查 `PASS`；允许创建 T-607 普通任务提交。已新增版本化 Agent MVP 固定验收矩阵、可机读的验收项—case—业务安全结果合同、确定性 Fake 运行器、六阶段失败定位、报告 Schema、独立 DeepSeek 补充格式和真实失败保留校验。Reviewer 首轮指出的 DeepSeek 草稿错误判定和攻击路径缺口已修复：`agent-response-draft-v1` 按 Schema、声明类型、当前证据 ID 子集及禁止业务对象字段判定；逐例记录 Prompt、模型、配置、数据集、耗时、网络状态和失败原因。固定集 31 项显式覆盖越权订单、伪造审批 ID、真实恢复入口的缺失 checkpoint、跨绑定 checkpoint、非可信恢复事件、批准前零写入、批准后幂等恢复、调整/拒绝零写入、模型超时/限流/Schema 漂移、工具超时/绑定漂移/未知写入状态。Reviewer 修复后相关专项 212 passed、全仓 380 passed 且 1 skipped；Release Manager 收尾再次连续运行两次固定集均 31/31 且稳定投影一致，相关专项与回归 126 项、文档 15 项、全仓 380 项通过且 1 项跳过，Ruff format（139 个文件）/check、mypy（138 个源文件）和 `git diff --check` 通过。DeepSeek 供应商不可用仍记为 `BLOCKED`、`passed=false`，不影响 Fake 门禁。未定义或实现 T-701～T-706，未改变版本、创建 Tag、推送或发布。

**阶段七出口状态**：2026-08-11 Reviewer 阶段出口审查 `PASS`；T-601～T-608 构成当前完整 Agent MVP。进程内 `AgentWorkflowService` 是 T-602～T-606 的单一受控组合入口：公开请求只含消息，可信上下文只含服务端会话、身份和已确认字段；入口内部持有计划校验器、一次性 permit、受控 continuation、EvidenceRecord 和 Gate 调用，不接受调用方或模型提供身份覆盖、工具步骤、permit、资格、审批决定、证据、workflow ID 或 Gate 结果。DeepSeek 只负责理解、受限结构化计划和基于本轮可信证据的回复草稿；状态机、静态工具与计划校验、确定性订单权限/资格规则、人工审批及 Response Gate 保留最终裁决权。标准低风险路径只写入一次并经 Gate 返回；高风险路径在人工审批前保持等待且零写入，批准仅恢复一次，调整进入 CLARIFYING 且零写入，拒绝只返回 Gate 放行的可信拒绝事实且零写入。固定验收集 `1.2.0` 连续两次 38/38 且稳定投影一致，阶段专项 135 项、全仓 389 passed/1 skipped、文档 15 项通过，Ruff format/check、mypy 和 `git diff --check` 通过。T-608 与生产 Web nginx 代理复验均获 Reviewer PASS；Docker Compose 构建、四服务健康、关键连通、日志和清理闭环已有实际记录。当前候选版本为 `1.0.0rc2` / `v1.0.0-rc.2`。T-701～T-706 未实现且未获生产化授权；本结论不等于正式版本发布。

### T-608 Agent HTTP API 与消费者页面接入

**完成状态**：2026-08-11 Reviewer 最终审查 `PASS`；T-608 已完成，允许创建普通任务提交。当前不修改项目版本、不创建 Tag、不推送或发布。

- Release Manager 收尾复测：T-608 HTTP/API、审批、DeepSeek 错误注入、Agent workflow、工具和回复草稿相关专项 57 passed；全仓 Python 398 passed、1 skipped；文档 21 passed；Ruff format（153 个文件）/check、mypy（152 个源文件）、前端 Prettier/ESLint/Vitest（17 passed）和生产构建、`git diff --check` 均通过。保留 1 条既有 Starlette TestClient 弃用警告；本轮未运行真实模型，采用已获 Reviewer 审查的同一工作区 digest 4/4 脱敏记录作为真实模型证据。

**设计状态**

- 2026-08-11：Reviewer 首轮 `CONDITIONAL PASS`；补充 HTTP 幂等合同、确定性 confirmed 字段签发、应用级唯一依赖图/审批恢复绑定和写后失败公开投影后，独立复审为 `PASS`（仅限设计），允许开始 T-608 实现。
- 历史受限和可联网重跑为 `BLOCKED 0/4` 与 `BLOCKED 3/4`，均不计通过并保留为历史事实。最终 Reviewer 送审在同一工作区 digest `ca171d5b816c25b515b2bc3fa940ece10aee94f35e5105961ce7a0ec03fa29f9` 下，以 `deepseek-v4-flash`、配置版本 `1`、数据集版本 `1.0.0` 于 `2026-08-11T10:35:36.103982+00:00` 经公开 HTTP 路径得到 4/4 `PASSED`；Reviewer 据此给出最终 `PASS`。报告不含 Key、推理链或敏感内部数据。

**目标**

将已完成的进程内 `AgentWorkflowService` 接入现有消费者 HTTP API 与页面，使用户默认使用 Fake/合成 Agent，并在服务端配置 DeepSeek API Key 后可明确选择和实际使用 DeepSeek Agent，同时保持全部确定性安全裁决边界。

**输入**

- T-601～T-607 已通过 Reviewer 的 Agent 状态机、计划、工具、证据、审批恢复和 Response Gate 能力。
- 现有 `/api/v1/conversations` 会话 API、消费者 React 页面与人工审批 API。
- T-204 DeepSeek/Fake ModelGateway 配置和安全失败合同。
- `docs/superpowers/specs/2026-08-11-t608-agent-http-ui-design.md`。

**输出**

- Fake/DeepSeek 模式能力查询与会话创建合同。
- 会话模式固定、服务端 ModelGateway 选择和 `AgentWorkflowService.handle()/resume()` 接入。
- 只公开安全状态、Gate 放行回复与引用的 HTTP DTO 投影。
- 消费者模式选择、模式徽标、模型状态与可行动失败提示。
- Fake、供应商错误注入、API/前端集成、安全回归和真实 DeepSeek HTTP 链路评测报告。

**依赖**

- T-601～T-607 与阶段七出口 Reviewer PASS。
- 复用现有消费者和审批 API，不修改其可信身份与人工决定边界。
- T-608 Reviewer 设计审查已通过；实现仍须遵守本任务全部接口、安全与测试合同。

**接口契约**

- `GET /api/v1/agent-modes` 仅返回 `fake/deepseek` 的配置与可选择状态，不返回 Key、Base URL、Prompt 或供应商细节。
- `POST /api/v1/conversations` 接受可选 `mode: fake | deepseek`；省略时默认 `fake`，额外字段拒绝。
- DeepSeek 未配置时创建返回 `409 AGENT_MODE_NOT_CONFIGURED`，不创建会话或调用网络。
- `POST /api/v1/conversations/{id}/messages` 仍只接受 `message`；模式、身份、turn、permit、工具、证据和 workflow 均由服务端提供。
- 消息 POST 必须携带版本化 `http-idempotency-v1` 的 `Idempotency-Key`：UUID v4，绑定可信 user/conversation/mode/path/message digest/turn，并原子记录 `PROCESSING | COMPLETED | FAILED_SAFE`；同绑定重放复用公开结果，冲突返回 409，写后失败或未知状态不得重放写操作。进程内 TTL/重启限制必须公开说明，key 不得承载或暴露 permit、workflow 或 evidence。
- 每轮先由现有确定性 `ReturnInformationCollectionService` 或等价已审计适配器签发和修订 confirmed order/reason/condition；模型只可提供候选，不能直接写入 `TrustedAgentContext`。字段不全时退货写操作保持 clarify/零写入，政策与授权订单只读路径按自身前置条件运行。
- 唯一应用 composition root 必须让 conversations/approvals router、AgentWorkflowFactory、AgentConversationService、ApprovalTaskService、checkpoint/service-case repository、HighRiskReturnWorkflowService、AgentWorkflowService 与 AgentSessionRegistry 复用同一依赖实例。审批决定按可信 conversation/turn/user/mode 绑定调用唯一 `resume()`；GET 永不恢复，绑定丢失、漂移或重启统一安全失败。
- 公开响应包含模式、Agent 状态、模型状态、公开原因码、行动提示和 Gate 放行内容；禁止公开 API Key、推理链、内部 permit、工具原始参数、EvidenceRecord、内部 Gate 原因或敏感审计。
- 会话模式不可变；切换模式必须创建新会话，不允许静默 DeepSeek→Fake fallback。

**验收标准**

- 默认 Fake 保持向后兼容，并通过 HTTP 实际调用 Fake AgentWorkflowService，不再走旧确定性会话编排。
- 配置 Key 后，DeepSeek 模式通过同一 HTTP 契约实际调用 DeepSeek AgentWorkflowService。
- 未配置、供应商不可用、超时、限流和结构化输出失败均进入明确安全状态，不伪装为模型成功，不执行未经验证计划。
- 前端默认标识“合成演示”，DeepSeek 成功仅在 `model_status=succeeded` 且 Gate 形成公开回复时展示。
- 页面、浏览器存储、HTTP 请求和响应均不含 Key、推理链、Prompt、permit、工具原始参数、内部证据或敏感审计。
- 状态机、计划校验、工具白名单、订单授权、资格规则、人工审批、幂等和 Response Gate 回归保持通过。
- 消费者 GET 无业务副作用；人工决定后只能由服务端可信绑定调用 `resume()`，重复恢复不创建第二条申请。
- 同一幂等 key 的并发/串行重试、同 key 不同 body、跨 conversation/user/mode、pending approval、写后草稿/Gate/网络失败及未知写入状态均有固定验证；最多一条申请且 GET 零副作用。
- 多轮字段收集、否定/更正历史、模型候选冲突、伪造 confirmed 字段与信息不全零写入通过；演示身份继续由服务端固定 `_DEMO_USER_ID`，不得声称生产认证。
- 高风险会话与审批工作台在同一依赖图完成 list→approve/adjust/reject→同会话查询；跨绑定伪造、重复决定、不同 Factory 实例和状态丢失均安全失败，批准后唯一申请，调整/拒绝零申请。
- 写已确认成功但草稿/Gate/网络失败时公开 `RESPONSE_UNAVAILABLE_AFTER_COMMIT`，写入未知时公开 `WRITE_OUTCOME_UNKNOWN`；重试和 GET 均不得重放写操作或泄露未经 Gate 校验事实。
- Fake、错误注入、API 和前端自动化测试全部通过，T-607 固定集无退化。
- 真实 DeepSeek 评测必须经 HTTP API 覆盖政策、低风险退货、高风险审批恢复和安全对抗代表路径；缺少 Key 为 `SKIPPED`，供应商/网络/限流失败为 `BLOCKED`，均不得记为通过。
- 在真实 DeepSeek 代表路径全部实际通过前，T-608 不得最终 PASS，不得宣称页面可实际使用 DeepSeek，也不得恢复 rc.2 候选发布。
- 不定义或实现 T-701～T-706，不修改版本号、Release、提交或 Tag。

**测试与评测**

- 单元：模式与默认值、模式不可变、配置脱敏、公开 DTO 白名单、错误状态映射、幂等绑定/冲突/状态投影、确定性 confirmed 字段签发及唯一依赖图保护。
- API/组件：Fake/DeepSeek 路由、模型五类失败、高低风险流程、同 key 并发与写后失败重试、字段修订、同一审批工作台恢复、绑定漂移安全失败、GET 无副作用和敏感字段拒绝。
- 前端：模式选择/禁用、模式徽标、五类失败提示、新会话切换和浏览器数据边界。
- 回归：T-607 固定集、Agent 内核、订单、资格、审批、恢复、Response Gate 及现有消费者 Fake 演示。
- 真实模型：只使用合成数据，经 HTTP 链路运行并记录模型/Prompt/配置/数据集、网络、耗时、公开结果、失败和脱敏审计关联。

## 11. 后续生产化编号预留

T-701～T-706 预留给 Agent MVP 通过后的生产化增强。本文件只保留编号，不定义名称、范围、依赖、版本或验收标准；任何任务启动前必须另行完成产品目标、安全影响和发布门禁设计。

## 12. 推荐执行顺序

```text
T-000 → T-001 → T-002
→ T-101 → T-102 → T-103 → T-104
→ T-201 → T-202 → T-203
→ T-301 → T-302 → T-303 → T-304
→ T-401 → T-402 → T-403 → T-404

Agent MVP：
T-601 → T-602 → T-603 → T-604 → T-605 → T-606 → T-607 → T-608
```

## 13. 第一版本发布检查

- [x] 所有 P0 任务均有验收记录。
- [x] 标准退货流程可重复完成。
- [x] 高风险审批流程可暂停、恢复并完成。
- [x] 重复提交、审批和恢复不会产生第二个售后申请。
- [x] 最终事实和结论可追溯到政策、订单、规则或业务结果。
- [x] 越权、无依据回答、虚假完成和审批绕过均被阻止。
- [x] 固定验收报告包含真实失败项和已知限制。
- [x] 文档明确区分产品目标、实际结果、模拟能力和未实现范围。

以上产品与安全验收项已由阶段七出口 PASS 关闭；它们不替代 Docker Compose 构建、启动、健康检查、连通性和清理闭环，也不构成发布授权。
