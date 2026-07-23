# T-104 模拟售后申请与重复保护设计

## 1. 目标与范围

T-104 为已授权、低风险且已符合资格的退货请求创建模拟售后申请，并保证同一业务请求不会产生多个申请。公开结果只在写入成功记录已确认存在时声明 `created`。

本任务不实现真实退款、数据库、HTTP 写接口、会话恢复、审批任务、Agent、工作流、界面或 T-201。高风险审批后的恢复创建属于后续流程能力，不在本任务内实现。

## 2. 固定输入与信任边界

- 订单必须是 T-102 产生的 `AuthorizedOrderFacts`；当前用户身份由独立 `ServiceCaseAccessContext` 注入，服务不接收原始所有者或用户提交的授权结论。
- 商品行必须存在于已授权订单中。
- 资格必须由独立服务端 `ServiceCaseEligibilityContext` 注入；服务不接受公开 payload 自报的 `eligible`、风险或审批状态。T-103 结果绑定实际订单、商品行、产品和规则版本，T-104 必须逐字段核对。
- 只有 `status=eligible`、`eligibility=eligible` 且 `requires_human_approval=false` 的资格结果可写入。
- 公开 payload 不包含 `workflow_id` 或幂等键；幂等边界由可信 `user_id + order_id + order_item_id` 规范化派生。T-001 已有种子申请使用同一可信边界导入，不改写原始固定数据。

## 3. 方案选择

采用可注入的进程内 `InMemoryServiceCaseRepository`，并由 T-001 `data/seed/service_cases/service_cases.v1.json` 初始化已有模拟申请。

- 不直接写回固定 JSON，避免污染版本化数据和测试间状态泄漏。
- 不新增 Mock Business 写入 HTTP API，避免扩大 T-104 到网络合同与外部写入边界。
- 仓库协议隔离读取、创建和失败模拟，使单元测试可覆盖写入失败，组件测试可走公开服务路径。

## 4. 公开合同与数据流

`ServiceCaseService.create(request, access_context, eligibility_context)` 接收冻结的公开请求、服务端身份上下文和服务端资格上下文；公开请求仅包含可信订单事实和目标商品行。

1. 校验订单商品行绑定与资格预条件；不满足时返回稳定 `blocked` 结果，且不调用仓库写入。
2. 基于可信用户、订单和商品行生成规范化、稳定的幂等键。
3. 查询该键已有的成功结果；命中时返回原申请和 `existing` 状态。
4. 未命中时调用仓库创建模拟申请。
5. existing 和 create 确认都必须是已持久化的 `created`，并严格绑定用户、订单、商品行和键；只有此时才返回申请编号。
6. 仓库异常、空确认或非 `created` 确认统一返回脱敏 `failed_safe`；最终确认校验和公开摘要构造也必须在同一异常边界中。空、空白或其他无法满足摘要 Schema 的畸形确认不携带申请编号，也不使用“已创建”或“已完成”文案。

公开响应 Schema 固定包含状态、稳定错误码（成功/已有时为空）、消息和可选申请摘要；失败及被拦截结果不得携带申请摘要。生成的申请只包含白名单业务字段，不扩散订单内部字段。

## 5. 幂等与编号

- 幂等键是确定性的内部值，不在公开响应中暴露。
- 同键重复调用返回首次已确认申请，不创建第二条记录。
- 用户、订单或商品行任一不同即是不同业务请求边界；公开调用方无法通过更换随机工作流绕过该边界。
- 新申请 ID 由内存仓库按确定性递增序列生成；测试中的新仓库从 `SC-SIM-001` 开始。T-001 的 `SC-DEMO-001` 为已有种子记录。
- 仓库在单一进程内以键索引并原子地执行“查找或创建”；若写后发生异常，后续使用同一稳定键只查询首次确认记录，不能随机换键创建第二条。跨进程、分布式并发与持久恢复不属于本任务。

## 6. 测试与验收

单元测试覆盖：

- 允许的低风险请求创建唯一申请；
- 同一请求重复调用返回同一 ID，仓库只保留一条；
- T-001 已有申请返回 `SC-DEMO-001`；
- 非 `eligible`、待核验、需审批或不绑定商品行不能写入；
- 写入抛错、空确认或错误确认都返回 `failed_safe`，公开序列化不含成功断言或申请 ID；
- 幂等键针对工作流、订单和商品行隔离；
- 输入、响应和状态/错误码组合 Schema 约束。

组件测试仅调用公开 `ServiceCaseService.create()`，并直接复用 T-002 `AC-FR07-N-001`、`AC-FR07-E-001`、`AC-FR07-E-002` 的结构化前置条件和实体，不依赖固定自然语言。

## 7. 预计文件

- `src/customer_service/service_cases/__init__.py`
- `src/customer_service/service_cases/schemas.py`
- `src/customer_service/service_cases/repository.py`
- `src/customer_service/service_cases/service.py`
- `tests/unit/service_cases/`
- `tests/component/service_cases/test_t002_service_case_cases.py`
- `README.md`
- `TASKS.md`
- `docs/CHANGELOG.md`
- `docs/task-reports/T-104.md`

## 8. 已知限制

- 仅模拟退货申请创建，不执行退款。
- 进程内存状态不跨服务重启保留；中断恢复和跨进程幂等属于后续任务。
- 不创建审批任务，也不处理审批后的恢复写入。
- 不引入自然语言解析或用户界面。
