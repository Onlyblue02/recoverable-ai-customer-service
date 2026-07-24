# T-201 诉求识别与流程引导设计

## 1. 目标与范围

T-201 以确定性规则识别政策咨询、订单查询、退货申请和未知诉求，并输出下一步路由或安全澄清/人工升级结果。它建立最小会话路由状态：当前阶段、是否已有进行中的退货任务和澄清次数。

本任务不实现 T-202 多轮信息收集、槽位修订、持久化检查点、Agent、模型调用、工作流引擎、审批、订单/政策/资格实际调用、售后申请写入、HTTP API 或界面。

## 2. 输入与信任边界

- `RoutingContext` 仅由服务端提供，包含当前 `stage`、`clarification_count` 和已有退货任务标志；公开消息不能指定已识别意图、路由、人工状态或业务执行状态。
- `RoutingRequest` 只接收用户消息；消息必须非空白，Schema 拒绝额外字段。
- 当前没有模型服务，因此识别器只使用可审计、版本化代码中的有限中文关键词和订单号模式；它不声称理解开放式自然语言。
- 路由器不调用任何 T-101～T-104 服务，也不创建业务副作用。

## 3. 方案

新增独立 `customer_service.routing` 模块：

- `schemas.py`：冻结输入、上下文、结果、阶段、意图、下一动作和稳定原因码。
- `service.py`：公开 `IntentRoutingService.route(request, context=...)`，只完成确定性识别和状态转换。

选择独立模块而非复用订单或政策服务，以保证未知输入不能意外触发业务操作，也让后续 T-202 能在不改变 T-201 合同的前提下扩展收集状态。

## 4. 规则优先级与结果

1. 若服务端上下文已表示进行中的退货任务，优先输出 `continue_return`；不会被普通补充文本、订单号或关键词重置。
2. 否则按固定优先级识别明确政策咨询、显式退货申请、订单查询、一般政策咨询和一般退货词。含“了解/咨询/查询/知道”并指向政策、规则或条件的表述，以及明确的“退货政策/规则/条件”，优先进入政策咨询；显式退货申请限于直接行为表达（如“我想/我要/申请退货、退款或退掉”），并优先于同句订单号和资格问句；订单查询必须含明确查询行为（如“查/查询/看看订单”或“订单状态”），订单号或“订单”名词本身不能抢占政策咨询。
3. 无法可靠匹配时为 `unknown`：
   - 当前澄清次数为 0：输出 `needs_clarification`，计数变为 1，只询问用户希望进行政策咨询、订单查询还是退货申请。
   - 当前澄清次数为 1 或更高：输出 `escalated`，计数固定为 2，要求人工处理。

确定性映射：

| 识别意图 | 下一动作 | 公开阶段 | 副作用 |
| --- | --- | --- | --- |
| `policy_question` | `policy_qa` | `ROUTED` | 无 |
| `order_query` | `order_query` | `ROUTED` | 无 |
| `return_request`（含订单号） | `collect_return_information` | `COLLECTING_INFORMATION` | 无 |
| `return_request`（缺订单号） | `collect_return_information` | `NEEDS_CLARIFICATION` | 无 |
| `continue_return` | `continue_return` | 保留上下文阶段 | 无 |
| `unknown`（首次） | `clarify_intent` | `NEEDS_CLARIFICATION` | 无 |
| `unknown`（第二次） | `escalate_human` | `ESCALATED` | 无 |

## 5. 安全与错误处理

- 所有低确定性、未知或歧义输入均不产生业务写入；结果明确 `business_operation_requested=false`。
- 已有退货连续性只来自可信上下文；消息无法伪造恢复、完成或审批状态。
- 结果消息不包含模型推理、订单事实、政策结论或申请创建声明。
- 所有状态、动作、错误码和字段组合由 Schema 验证，输入/结果拒绝额外字段。

## 6. 验证

单元测试覆盖：

- 政策、订单、退货和未知意图；
- 进行中退货优先于重新分类；
- 两轮未知输入的澄清和升级；
- 关键词边界、稳定重复结果、输入/结果 Schema；
- 混合退货表达、仅提订单号的政策咨询，以及含退货上下文的明确订单状态查询；
- “我想/我要了解、查询或知道退货政策/规则”的咨询表达不得被识别为退货申请；
- 未知输入不请求业务操作。

组件测试读取 T-002 `AC-FR02-N-001` 和 `AC-FR02-E-001`，使用语义标签和用例示例调用公开 `IntentRoutingService.route()`；不依赖单一固定措辞。

## 7. 预计文件

- `src/customer_service/routing/__init__.py`
- `src/customer_service/routing/schemas.py`
- `src/customer_service/routing/service.py`
- `tests/unit/routing/`
- `tests/component/routing/`
- `README.md`
- `TASKS.md`
- `docs/CHANGELOG.md`
- `docs/task-reports/T-201.md`

## 8. 已知限制

- 识别器是有限关键词/模式规则，不是通用自然语言理解或模型分类器。
- 不保存会话状态；调用方必须提供可信路由上下文。跨刷新恢复与槽位收集属于后续任务。
- 阶段二遗留：联网环境下的 `uv lock --check` 以及 Docker Compose 启动、健康检查、初始化尚未验证；这些不阻塞 T-201，但须在 v1.0.0 前关闭或明确记录。
