# Docker Compose 发布验证清单与结果模板

本模板用于候选版或正式版发布前的受控环境验证。填写人必须记录实际命令、输出摘要、日志位置和结论；`NOT_RUN`、`BLOCKED` 或失败不得写成通过。

## 1. 基本信息

| 字段 | 记录 |
| --- | --- |
| 验证日期/时区 | `<YYYY-MM-DD HH:mm TZ>` |
| 验证人 | `<name>` |
| Git commit | `<full hash>` |
| 工作区状态 | `<clean/dirty；如 dirty 列出文件>` |
| 项目版本 | `<pyproject.toml [project].version>` |
| 候选 Tag | `<none 或 vX.Y.Z-rc.N>` |
| 操作系统/架构 | `<OS / amd64 / arm64>` |
| Docker Engine | `<version>` |
| Docker Compose | `<version>` |
| Docker Hub/镜像源 | `<registry、镜像缓存或代理>` |
| 网络状态 | `<stable/degraded/unavailable + 证据>` |
| 开始前项目容器 | `<none 或列表>` |

允许的结果值：`PASS`、`FAIL`、`BLOCKED`、`NOT_RUN`。只有实际执行且满足预期的项目可以标为 `PASS`。

## 2. 发布前检查

| 检查项 | 命令 | 预期 | 实际结果 | 状态 | 证据/日志 |
| --- | --- | --- | --- | --- | --- |
| 工作区与提交 | `git status --short`、`git log -1 --oneline` | 发布范围明确 | `<填写>` | `<状态>` | `<路径>` |
| 唯一版本源 | 读取 `pyproject.toml` | 与候选版本一致 | `<填写>` | `<状态>` | `<路径>` |
| 锁文件 | `uv lock --check` | 退出码 0 | `<填写>` | `<状态>` | `<路径>` |
| Compose 配置 | `docker compose -f deploy/compose.yaml config --quiet` | 退出码 0 | `<填写>` | `<状态>` | `<路径>` |
| 初始清洁状态 | `docker compose -f deploy/compose.yaml ps -a` | 无本项目遗留容器 | `<填写>` | `<状态>` | `<路径>` |

## 3. 构建与启动

```powershell
docker compose -f deploy/compose.yaml build --pull
docker compose -f deploy/compose.yaml up -d
docker compose -f deploy/compose.yaml ps
```

| 检查项 | 预期 | 实际结果 | 状态 | 证据/日志 |
| --- | --- | --- | --- | --- |
| 基础镜像拉取 | 所有 manifest/layer 完整获取 | `<填写>` | `<状态>` | `<路径>` |
| 镜像构建 | 全部服务构建成功，记录镜像 ID/digest | `<填写>` | `<状态>` | `<路径>` |
| Compose 启动 | 命令退出码 0 | `<填写>` | `<状态>` | `<路径>` |
| 容器状态 | 全部必需容器 running/healthy | `<填写>` | `<状态>` | `<路径>` |
| PostgreSQL | ready，初始化无错误 | `<填写>` | `<状态>` | `<路径>` |

## 4. 健康检查与连通性

实际 URL、端口和服务名必须以 `deploy/compose.yaml` 为准，不得照抄占位值。

| 检查项 | 命令或方法 | 预期 | 实际结果 | 状态 | 证据/日志 |
| --- | --- | --- | --- | --- | --- |
| Customer Service 存活 | `GET /health/live` | HTTP 200 与预期 JSON | `<填写>` | `<状态>` | `<路径>` |
| Mock Business 存活 | `GET /health/live` | HTTP 200 与预期 JSON | `<填写>` | `<状态>` | `<路径>` |
| Web 可访问 | 浏览器或 HTTP 请求 | 页面加载成功 | `<填写>` | `<状态>` | `<路径>` |
| Web→后端 | 执行最小合成请求 | 请求成功且无错误代理 | `<填写>` | `<状态>` | `<路径>` |
| 后端→Mock Business | 执行授权合成订单查询 | 服务间调用成功 | `<填写>` | `<状态>` | `<路径>` |
| 后端→PostgreSQL | 应用初始化/连接检查 | 连接成功，无迁移或 Schema 错误 | `<填写>` | `<状态>` | `<路径>` |
| 最小业务冒烟 | 政策、订单或标准退货合成路径 | 结果符合固定预期 | `<填写>` | `<状态>` | `<路径>` |

## 5. 日志检查

```powershell
docker compose -f deploy/compose.yaml logs --no-color
docker compose -f deploy/compose.yaml ps
```

- [ ] 已保存构建日志。
- [ ] 已保存启动和健康检查日志。
- [ ] 已检查 crash、restart loop、traceback、连接拒绝和初始化失败。
- [ ] 日志证据已脱敏，不包含 API Key、密码、Token 或真实个人数据。
- [ ] 已记录所有 warning，并说明是否影响发布。

日志结论：`<填写>`
日志位置：`<填写>`

## 6. 清理闭环

```powershell
docker compose -f deploy/compose.yaml down
docker compose -f deploy/compose.yaml ps -a
```

| 检查项 | 预期 | 实际结果 | 状态 | 证据/日志 |
| --- | --- | --- | --- | --- |
| Compose down | 退出码 0 | `<填写>` | `<状态>` | `<路径>` |
| 容器残留 | 无本项目容器 | `<填写>` | `<状态>` | `<路径>` |
| 网络残留 | 无非预期项目网络 | `<填写>` | `<状态>` | `<路径>` |
| 数据卷处理 | 与发布计划一致；不得误删需保留数据 | `<填写>` | `<状态>` | `<路径>` |

## 7. 最终结论

| 项目 | 结论 |
| --- | --- |
| 构建 | `<PASS/FAIL/BLOCKED/NOT_RUN>` |
| 启动 | `<PASS/FAIL/BLOCKED/NOT_RUN>` |
| 健康检查 | `<PASS/FAIL/BLOCKED/NOT_RUN>` |
| 服务连通性 | `<PASS/FAIL/BLOCKED/NOT_RUN>` |
| 清理闭环 | `<PASS/FAIL/BLOCKED/NOT_RUN>` |
| 总体发布建议 | `<GO/NO-GO>` |

未关闭项：

1. `<问题、责任人、下一步和证据要求>`

Release Manager 结论：`<填写>`
Reviewer/项目所有者确认：`<填写；缺失时必须标记未确认>`

## 8. 当前发布准备状态（2026-08-11）

- 本轮 Docker Compose 构建、服务启动、健康检查、服务连通性和清理闭环均已完成；完整实际记录见 `docs/release-validation-docker-2026-08-11.md`。
- 后续候选或正式发布若改变 Dockerfile、Compose、镜像输入、运行时配置或数据，必须在受控环境重新填写本模板，不得复用旧记录。
- Docker 技术验证通过不等于正式发布授权；仍须完成版本、测试、文档与所有者授权门禁。
