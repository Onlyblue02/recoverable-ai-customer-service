# T-102 订单查询与权限边界设计

## 1. 目标与范围

T-102 基于 T-001 数据集 `racs-core-business-data` 版本 `1.0.0`，实现独立、确定性的订单查询服务。服务必须同时接收当前用户 ID 与订单 ID，由可信 Mock Business 数据边界验证订单归属，只在授权成功时返回明确白名单内的订单事实。

本任务不实现自然语言抽取、退货资格规则、售后申请写入、Agent、LangGraph、会话、数据库持久化或界面，也不开始 T-103。T-002 的结构化语义实体用于组件验证，不比较固定自然语言措辞。

## 2. 固定输入与信任边界

- 用户和订单只从 `data/manifest.json` 声明的 T-001 `seed/users` 与 `seed/orders` 文件加载。
- 数据集版本固定为 `1.0.0`。
- 公开查询 payload 只包含可选 `order_id`；可信 `current_user_id` 由独立的服务端 `OrderAccessContext` 注入，不能被 payload 覆盖。
- 缺少或只有空白的订单 ID 时，公开服务直接返回补充结果，不调用 Gateway。
- Mock Business 仓储是订单存在性和归属判断的可信业务边界。主应用、模型或调用方均不得重新判断或覆盖其授权结果。
- Mock Business API 只在授权成功后返回订单事实；不存在与越权响应不包含任何订单字段。

## 3. 方案选择

采用最小 Mock Business HTTP 边界：固定 JSON 仓储、单一只读订单端点、主应用 HTTP Gateway 和公开 `OrderQueryService`。

仅使用进程内仓储虽然文件更少，但不能验证项目架构规定的 Mock Business API 边界。立即引入 PostgreSQL、迁移和完整订单领域模型则超出 T-102。当前方案使用现有 FastAPI 与 HTTPX 依赖，只建立订单读取所需的最小纵向路径。

## 4. 组件设计

### Mock Business 仓储

仓储从 manifest 解析用户和订单文件，验证：

- manifest 和文件的数据集版本一致；
- 用户 ID 与订单 ID 唯一；
- 每个订单所有者存在于用户集合；
- 必要订单与商品行字段满足类型化 Schema。

`lookup(current_user_id, order_id)` 的顺序固定为：先查订单是否存在，再在数据源边界比较订单所有者。返回 `FOUND`、`NOT_FOUND` 或 `UNAUTHORIZED`，且只有 `FOUND` 携带内部订单记录。

### Mock Business API

新增 `GET /orders/{order_id}`，请求必须包含 `current_user_id` 查询参数。端点把两个标识原样交给仓储：

- 授权成功返回 HTTP 200 和白名单订单事实；
- 不存在与越权均返回 HTTP 404、错误码 `ORDER_UNAVAILABLE` 和相同安全文案，避免公开订单枚举信号。

该失败响应只包含稳定错误码和安全消息，不包含商品、金额、状态、时间或所有者；仓库内部仍保留 NOT_FOUND/UNAUTHORIZED 区分。

### HTTP Gateway

主应用 Gateway 接收可信上下文中的 `current_user_id` 与 payload 中的规范化 `order_id`，向 Mock Business API 发起一次只读请求，将 200/404 映射为类型化边界结果。HTTP 200 响应只有在 Schema 有效且响应 `order_id` 与本次请求完全一致时才能成为 `FOUND`；不一致属于下游合同错误。HTTP、JSON、Schema 与下游合同错误均被规范化为内部 Gateway 错误。它不读取 T-001 文件，不判断归属，也不补造订单字段。

### 公开订单服务

`OrderQueryService.query()` 是 T-102 的公开服务路径：

1. 检查订单 ID 是否缺失或只有空白；若是，返回 `MISSING_ORDER_ID` 且不调用 Gateway。
2. 将独立权限上下文中的当前用户 ID 与 payload 中的订单 ID 同时传给 Gateway。
3. 将 Gateway 的 `NOT_FOUND` 或 `UNAUTHORIZED` 映射为相同公开 `ORDER_UNAVAILABLE` 结果。
4. 仅在 `FOUND` 时返回授权订单快照。
5. 捕获下游异常并返回固定 `ORDER_LOOKUP_UNAVAILABLE`，不公开异常文本。

权限判断和字段选择均由确定性代码完成，不使用模型。

## 5. 结构化结果与字段白名单

公开结果状态：

- `FOUND`：授权成功，`error_code=None`，存在订单快照。
- `MISSING_ORDER_ID`：错误码 `MISSING_ORDER_ID`，订单快照为空。
- `ORDER_UNAVAILABLE`：错误码 `ORDER_UNAVAILABLE`，订单快照为空，不区分不存在与越权。
- `DEPENDENCY_FAILURE`：错误码 `ORDER_LOOKUP_UNAVAILABLE`，订单快照为空，消息固定且脱敏。

结果 Schema 验证状态、错误码和订单快照三者一致，拒绝失败结果携带订单事实。

授权订单快照白名单仅包含：

- `order_id`、`status`、`placed_at`、`delivered_at`、`currency`、`total_amount`；
- 商品行的 `order_item_id`、`product_id`、`quantity`、`unit_price` 和 `line_total`。

不返回所有者 `user_id`、`scenario_tags`、`business_purpose`、`expected_behavior`、`synthetic_issue` 或任意未声明字段。公开 DTO 使用 `extra="forbid"`，订单快照由可信内部记录显式逐字段构造，不直接序列化原始 JSON。

## 6. T-002 验收映射

组件测试直接读取 `data/evaluation/retrieval/cases.v1.json`：

| 用例 | 预期结果 |
| --- | --- |
| `AC-FR04-N-001` | `FOUND`；返回 `ORD-NORMAL-001`、`delivered` 与 `129.00 CNY` |
| `AC-FR04-E-001` | `MISSING_ORDER_ID`；不调用 Gateway |
| `AC-FR04-E-002` | `ORDER_UNAVAILABLE`；不返回或构造订单事实 |
| `AC-FR04-E-003` | 同一 `ORDER_UNAVAILABLE`；不返回商品、金额、时间或所有者 |

测试使用 `initial_state.requesting_user_id` 和 `required_entities.order_id` 构造查询，并检查终态 `must_include`、`must_not_include` 的业务语义，不依赖示例措辞完整相等。

## 7. 测试设计

单元测试覆盖：

- 缺少和空白订单 ID 不调用 Gateway；
- 公开 payload 拒绝身份和授权字段，服务总是从独立上下文取得当前用户 ID；
- FOUND 与统一 ORDER_UNAVAILABLE 的稳定映射及仓库内部状态区分；
- 下游异常稳定降级且不泄露异常文本；
- 200 响应订单 ID 与规范化请求 ID 严格绑定，串单响应不得成为 FOUND；
- 失败结果不能携带订单事实；
- 数据版本不一致、重复 ID、悬空订单所有者和缺失文件明确失败；
- 白名单快照不包含原始数据内部字段。

组件测试通过 FastAPI TestClient、HTTP Gateway、真实 Mock Business 端点和固定 JSON 仓储调用公开 `OrderQueryService.query()`，覆盖全部四个 T-002 FR-04 用例以及字段泄露断言。

## 8. 预计修改文件

实现：

- `src/customer_service/tools/__init__.py`
- `src/customer_service/tools/schemas.py`
- `src/customer_service/tools/order_tool.py`
- `src/customer_service/infrastructure/clients/mock_business.py`
- `src/mock_business/schemas.py`
- `src/mock_business/repository.py`
- `src/mock_business/routes/__init__.py`
- `src/mock_business/routes/orders.py`
- `src/mock_business/main.py`
- `pyproject.toml`
- `uv.lock`

测试：

- `tests/unit/tools/test_order_tool.py`
- `tests/unit/mock_business/test_order_repository.py`
- `tests/component/tools/test_order_acceptance_cases.py`

记录：

- `README.md`
- `TASKS.md`
- `docs/task-reports/T-102.md`
- `docs/CHANGELOG.md`
- 本设计文档

不修改 T-001/T-002 固定数据或用例，不创建 T-103、Agent、工作流、资格规则或界面，不修改项目版本，不提交、不创建 Tag、不推送远程。

## 9. 验证与状态口径

按测试先行顺序先运行新增 T-102 测试并记录缺少实现时的预期失败，再完成实现。实现后运行 T-102 专项测试、T-001/T-002/T-101 阶段基线、全仓 pytest、Ruff format/check 与 mypy；依赖元数据变更后同时运行锁文件校验。

执行者验证通过后，`TASKS.md` 与任务报告只能记录“待 Reviewer”，不得标记 Reviewer PASS、阶段二发布或 T-103 已开始。
