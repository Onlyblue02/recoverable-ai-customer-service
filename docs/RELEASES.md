# 阶段发布与版本管理

## 1. 唯一项目版本号

`pyproject.toml` 的 `[project].version` 是 RACS 唯一项目版本号来源。当前候选版本为 PEP 440 格式的 `1.0.0rc3`，对应本地 annotated Tag `v1.0.0-rc.3`；既有 `v1.0.0-rc.2` 标签保留不移动。T-608 已通过 Reviewer，`v0.5.0` 仍是最近正式版本。

- Web 是项目内部私有包，不维护独立项目版本号。
- Changelog、任务报告、Git 标签和远程 Release 只引用该版本，不成为新的版本源。
- `dataset_version`、政策版本、规则版本、Prompt 版本和工作流版本是独立制品版本，不代表项目版本。
- `src/customer_service/main.py` 与 `src/mock_business/main.py` 从 `customer_service.version` 读取该唯一版本源；发布检查仍须确认公开 API 展示版本与项目版本一致。

项目版本采用语义化版本格式。版本提升只能作为经批准的发布准备操作进行，不得仅因任务开始或进入规划阶段而提升。

## 2. 阶段版本规划

下表是发布规划，不代表任务完成、Reviewer 通过或版本已发布：

| 计划版本 | 任务范围 | 阶段目标 | 当前发布状态 |
| --- | --- | --- | --- |
| `v0.1.0` | T-000 | 工程基线 | 未单独发布：作为阶段一前置基线纳入 `v0.2.0` |
| `v0.2.0` | T-001～T-002 | 产品基线 | 已发布：阶段一 Reviewer 复审 PASS，2026-07-20 |
| `v0.3.0` | T-101～T-104 | 基础业务能力 | 已发布：阶段二 Reviewer PASS，2026-07-23 |
| `v0.4.0` | T-201～T-204 | AI 售后流程与模型适配 | 已发布：阶段三 Reviewer PASS，2026-07-27 |
| `v0.5.0` | T-301～T-304 | 人工协作与恢复 | 已发布：阶段四 Reviewer PASS，2026-07-27 |
| `v1.0.0` | T-401～T-404 | 完整 MVP | 最近正式版本仍为 `v0.5.0`；尚未授权正式发布 |
| `v1.0.0-rc.2` | 历史候选范围 | 既有本地候选 | 标签保留不移动；不作为当前候选版本 |
| `v1.0.0-rc.3` | T-601～T-608 及已审查 Docker 交付修复 | 完整 Agent MVP、消费者 Agent 接入与候选交付验证 | 全部任务与 Docker 闭环均有 Reviewer PASS 和实际记录；本地候选发布，未推送或正式发布 |

### v1.0.0-rc.3 候选版与正式版晋级

T-401～T-404 已完成并通过 Reviewer；Python、前端、确定性 Fake、DeepSeek 真实模型评测链路以及 `uv.lock` 检查已有实际证据。DeepSeek 固定评测为 10/11，保留 1 个已记录失败案例，不能写成全量用例通过。

2026-08-11 已在全新纯 ASCII 副本完成 Docker Desktop/Engine、Compose、Buildx、镜像拉取、构建、启动、健康检查、服务连通、日志和清理闭环。该验证先修复后端镜像遗漏运行时 `config/`/`data` 及 Windows 宿主端口冲突，随后以提交 `5b24609` 为原始字节基线、以逐文件 SHA-256 manifest 绑定 `deploy/web.Dockerfile` 和 `deploy/nginx.conf` 的 nginx 修复。修复后 PostgreSQL、两个 API 与 Web 均健康；Web 同源 `/api/v1/agent/modes`、Web→API、API→Mock/PostgreSQL、Fake 政策/低风险/高风险审批恢复均通过，`down --volumes --remove-orphans` 后容器、网络和命名卷无残留。DeepSeek Docker 路径因 Compose 未注入凭据而未执行，未计为通过。完整实际证据见 [Docker 发布验证记录](release-validation-docker-2026-08-11.md) 与 [post-fix 输入 manifest](evaluations/docker-compose-5b24609-post-fix-manifest.json)。

晋级正式 `v1.0.0` 必须同时满足：

1. 以正式发布提交重跑 Docker Compose 闭环；只要 Dockerfile、Compose、镜像输入、运行时配置或数据发生变化，既有验证记录不得替代该复跑。
2. 重新运行 `uv lock --check`、Python、前端、Fake/真实模型专项、版本和文档一致性门禁。
3. 真实 DeepSeek HTTP 代表路径保持脱敏且可追溯；缺少 Key、供应商不可用、网络失败或限流仍必须记为 `SKIPPED` 或 `BLOCKED`，不得记为通过。
4. Release Manager 核对正式提交、Docker 记录与测试证据，且项目所有者明确授权正式发布、正式 Tag 和任何远程操作。

“未发布”只说明发布证据不足，不否定 `TASKS.md` 中已有的任务验收记录。

### 完整 Agent MVP 与下一版本建议

T-601～T-607 已通过各任务 Reviewer 审查及阶段七出口审查。当前实际能力是进程内、受控的 Agent MVP：DeepSeek 仅负责意图理解、受限结构化计划和基于本轮可信证据的回复草稿；它不能直接调用工具，也不能决定订单权限、资格、风险、审批、业务写入或最终公开回复。显式状态机、静态工具/计划校验器、确定性订单权限与资格规则、人工审批链路和 Response Gate 保留最终裁决权。

阶段七固定集 `1.2.0` 连续两次均为 38/38 且稳定投影一致；阶段专项 135 项、全仓 389 passed/1 skipped、文档 15 项通过。DeepSeek 独立补充仍保留 `BLOCKED / DEEPSEEK_PROVIDER_UNAVAILABLE`，不计为通过；既有真实失败案例继续保留。当前状态、证据 authority、工作流组合和审计仍为进程内实现，不提供生产持久化、跨进程恢复、生产认证或 SLA。T-701～T-706 未实现，只是后续生产化增强的预留编号。

版本策略建议（本轮不执行）：

1. 当前候选版本为 PEP 440 `1.0.0rc3` / Git Tag `v1.0.0-rc.3`，承载 T-601～T-608 与已审查 Docker 修复；既有 `v1.0.0-rc.2` 标签保留不移动。
2. 满足本节正式晋级条件并获得项目所有者授权后，才建议创建正式 `v1.0.0`。
3. 正式 Tag、推送和远程 Release 均须项目所有者另行明确授权。

## 3. 任务报告

每个进入验收的任务必须维护 `docs/task-reports/T-xxx.md`。格式和字段要求见 [task-reports/README.md](task-reports/README.md)。

任务报告是发布核对依据，但不能单独证明阶段可发布。Reviewer 结论必须注明结论、日期和证据位置；缺少任一项时按“未提供/待核验”处理。

## 4. 正式发布门禁

只有同时满足以下条件，计划版本才可标记为可发布：

1. 版本范围内全部任务均有任务报告，且状态与 `TASKS.md` 一致。
2. 每项任务均有明确、可追溯的 Reviewer 通过结论。
3. 阶段要求的测试已经实际运行，任务报告记录命令、日期和实际结果。
4. 文档描述、任务状态、Reviewer 结论、测试结果和工程实际能力一致。
5. `docs/CHANGELOG.md` 已准确整理该版本的可核实变化和已知限制。
6. `[project].version` 已按计划更新，且所有展示或派生版本均与其一致。
7. 没有把设计目标、计划指标、Mock 能力或未完成功能描述成实际结果。
8. 项目所有者明确授权本次发布动作。
9. 在受控发布环境实际记录 `uv lock --check` 与 `docker compose -f deploy/compose.yaml config --quiet` 的输出；若 Compose 将作为交付方式，还应记录启动、健康检查和初始化结果。

任一条件不满足时，Release Manager 必须停止发布并列出阻塞项。

## 5. 发布操作顺序

1. 核对任务范围、任务报告和 Reviewer 证据。
2. 重新运行阶段要求的验证，并记录实际结果。
3. 核对工程能力、README、任务状态和 Changelog。
4. 经项目所有者确认后，将 `[project].version` 更新为计划版本。
5. 将 `Unreleased` 中属于该版本的内容整理为带发布日期的正式条目。
6. 再次执行版本和文档一致性检查。
7. 仅在项目所有者另行确认后，执行提交、标签、`git push` 或创建远程 Release。

不得覆盖已有正式版本条目或重写历史发布记录。需要更正时新增说明或后续补丁版本。

## 6. 一致性检查

每次候选发布至少检查：

- `[project].version` 与计划版本一致；
- 不存在未经说明的其他项目版本源；
- 阶段任务范围与本文件映射一致；
- `TASKS.md` 和任务报告状态一致；
- Reviewer 结论有证据且没有被推断；
- 测试结果来自实际执行，而不是验收目标；
- Changelog 没有提前创建未发布版本的正式记录；
- 已知限制、失败和未完成范围仍被如实保留。
- 锁文件与 Compose 检查有实际日志和明确结果；历史离线缓存缺包、PATH 缺少 Docker CLI 或命令失败均不是通过证据，后续复测必须明确标注其是否已被取代。

## 7. 可重复发布检查

在具备包索引（或完整缓存）和 Docker CLI 的受控发布环境依次执行，并将命令输出保存到发布记录：

```text
uv lock --check
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml up --build -d
docker compose -f deploy/compose.yaml ps
```

之后按 `deploy/compose.yaml` 的健康检查和初始化说明验证服务，再以 `docker compose -f deploy/compose.yaml down` 收尾。2026-08-11 已按这一闭环实际完成验证并保存证据；若交付配置变化，必须按同一清单重新验证。逐项格式见 [Docker 发布验证模板](DOCKER_RELEASE_VALIDATION_TEMPLATE.md)，实际记录见 [2026-08-11 Docker 发布验证记录](release-validation-docker-2026-08-11.md)。
