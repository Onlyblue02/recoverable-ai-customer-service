# v1.0.0 发布环境验证记录（2026-07-28）

## v1.0.0-rc.1 决定（2026-07-29）

- T-401～T-404 已完成并通过 Reviewer。
- Python、前端、确定性 Fake 和 DeepSeek 真实模型专项已有实际评测证据；DeepSeek 固定结果为 10/11，并保留 1 个失败案例。
- `uv.lock` 已同步且 `uv lock --check` 通过。
- Docker Hub 网络访问失败，Docker 构建、Compose 启动、健康检查、初始化和服务连通闭环均未完成，不能记录为通过。
- 允许准备本地候选版本 `v1.0.0-rc.1`；`v0.5.0` 仍是最近正式版本，不发布正式 `v1.0.0`，不推送远程。

正式 `v1.0.0` 仅可在稳定 Docker 环境完成本文“关闭条件”、重新运行全部非 Docker 门禁、核对版本与文档一致性，并取得项目所有者明确授权后晋级。

候选版准备复测实际结果：

- `uv lock` 将 editable 项目包从 `0.5.0` 更新为 `1.0.0rc1`；`uv lock --check` 输出 `Resolved 65 packages in 2ms` 并通过。
- 全仓 Python 291 项、model gateway 专项 10 项、文档专项 12 项通过；保留 1 条既有 Starlette TestClient 上游弃用警告。
- Ruff format/check、mypy（106 个源文件）、Prettier、ESLint、前端 Vitest 10 项、生产构建和 `git diff --check` 通过。
- 本次未重试 Docker；此前 Docker Hub manifest EOF 仍是当前阻塞，不能据此推断构建或健康检查成功。

## 结论

**Docker Hub 网络阻塞，未通过发布验证。** T-404 已通过独立 Reviewer 审查；本报告只记录发布环境执行，不授权发布、创建 Tag 或推送。

## 当前发布状态（2026-07-28）

- `uv lock --check` 已通过，锁文件一致性阻塞已关闭。
- Docker CLI、Engine 和 Compose config 已可用；最新的 `docker pull docker/dockerfile:1` 在读取 Docker Hub manifest 时返回 EOF。预拉取未成功，因此本轮没有重新执行 Compose 构建、状态查看或健康检查。
- `docker compose -f deploy/compose.yaml down` 已成功，最终 `ps` 无项目容器。
- 项目所有者尚未授权 `v1.0.0` 发布。

## 阻塞处理结果

### uv.lock：已关闭（当前结论）

执行：

```powershell
uv lock
uv lock --check
```

实际输出：

```text
Resolved 65 packages in 1.55s
Updated recoverable-ai-customer-service v0.2.0 -> v0.5.0
Resolved 65 packages in 2ms
```

锁文件差异仅为 editable 项目包 `recoverable-ai-customer-service` 的版本从 `0.2.0` 更新为 `0.5.0`；未增加、删除或变更第三方解析包。随后全仓 Python 测试 `289 passed`（1 条既有 Starlette TestClient 弃用警告）、Ruff format/check 和 mypy（106 个源文件）均通过。

### Docker BuildKit：环境阻塞，未关闭（当前结论）

诊断环境：Docker Desktop `4.79.0`、Engine `29.5.3`、Buildx `v0.34.1-desktop.1`、builder `desktop-linux`、BuildKit `v0.30.0`。Docker Engine 正常运行，`docker compose -f deploy/compose.yaml config --quiet` 退出码 `0`。

当前会话未设置 `DOCKER_*`、`BUILDKIT_*`、`BUILDX_*` 或 `COMPOSE_*` 环境变量；Docker 配置仅检测到常规字段名，未读取或记录凭据；`docker buildx inspect desktop-linux` 显示 builder 状态为 `running`。

重启 Docker Desktop 后，使用未修改的项目命令执行：

```powershell
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml up --build -d
docker compose -f deploy/compose.yaml ps
```

`config --quiet` 通过；`up --build -d` 在加载 bake 定义之后稳定失败：

```text
failed to dial gRPC: rpc error: code = Internal desc = rpc error: code = Internal desc = header key "x-docker-expose-session-sharedkey" contains value with non-printable ASCII characters
```

`ps` 无项目容器，因此 `racs-api`、`mock-business-api`、`postgres`、`web` 的健康检查及服务连通性未执行。随后：

```powershell
docker compose -f deploy/compose.yaml down
docker compose -f deploy/compose.yaml ps
```

`down` 成功，最终 `ps` 无项目容器。错误发生在 Dockerfile 指令执行之前的 Docker Desktop/BuildKit Compose bake 会话 header 处理层；现有证据指向环境故障而非项目 Compose/Dockerfile 配置。不得通过禁用安全机制或修改项目部署配置规避该问题。

### 纯 ASCII 路径 Compose 复测：历史网络阻塞

- 执行时间：`2026-07-28T19:19:20.0052665+08:00`。
- 实际项目路径：`C:\Temp\racs-v100-release-verify`。这是从原工作区创建的临时验证副本；未修改原项目业务代码、Dockerfile 或 Compose 文件，副本排除了 `.env`、虚拟环境、Git 元数据和常规缓存。
- 环境：Docker Desktop `4.79.0`、Docker Client/Engine `29.5.3`、Buildx `v0.34.1-desktop.1`、builder `desktop-linux`（`running`）、BuildKit `v0.30.0`。

实际命令与结果：

```powershell
docker compose -f C:\Temp\racs-v100-release-verify\deploy\compose.yaml config --quiet
# 退出码 0

docker compose -f C:\Temp\racs-v100-release-verify\deploy\compose.yaml up --build -d
# 退出码 1

docker compose -f C:\Temp\racs-v100-release-verify\deploy\compose.yaml ps
# 无项目容器
```

构建已越过原先 `x-docker-expose-session-sharedkey` 的 Bake 会话阶段，但在请求 Docker Hub BuildKit frontend 授权 token 时失败：

```text
failed to authorize: failed to fetch oauth token: Post "https://auth.docker.io/token": dial tcp 199.16.156.39:443: connectex: A connection attempt failed because the connected party did not properly respond after a period of time, or established connection failed because connected host has failed to respond.
```

因此 `postgres`、`racs-api`、`mock-business-api`、`web` 均未创建或启动；容器状态、健康检查、`racs-api`/`mock-business-api` 健康接口、PostgreSQL 就绪检查、Web 可访问性和服务间连通性均为**未执行**，不能记录为通过。

```powershell
docker compose -f C:\Temp\racs-v100-release-verify\deploy\compose.yaml down
# 退出码 0

docker compose -f C:\Temp\racs-v100-release-verify\deploy\compose.yaml ps
# NAME  IMAGE  COMMAND  SERVICE  CREATED  STATUS  PORTS（无项目容器）
```

清理已完成，无项目容器残留。该次复测未出现原 BuildKit header 错误，但在 Docker Hub 授权 token 请求时网络超时；其结果已被下述最新预拉取复测补充。

### Dockerfile frontend 预拉取：镜像仓库网络阻塞（当前结论）

- 执行日期：`2026-07-29`。
- 工作目录：`C:\Temp\racs-v100-release-verify`（纯 ASCII 临时验证副本）。
- 命令：`docker pull docker/dockerfile:1`。
- 结果：退出码非零，未拉取成功。

```text
Error response from daemon: failed to resolve reference "docker.io/docker/dockerfile:1": failed to do request: Head "https://registry-1.docker.io/v2/docker/dockerfile/manifests/1": EOF
```

由于 BuildKit frontend 镜像未能预拉取，本轮未重新执行 `docker compose -f deploy/compose.yaml up --build -d`、`ps` 或任何服务健康/连通性检查。需要在能稳定访问 Docker Hub（或提供受控镜像缓存）的 Docker 环境中，对未修改的 Compose 文件完成预拉取、构建、启动和全部健康验证。

## 历史首次运行（已被后续复测取代）

首次受限会话运行时，`uv lock --check` 曾因 editable 项目包版本未同步而退出码 `1`，且 PATH 未发现 Docker CLI。这些结果已被本记录的当前结论取代，不代表当前锁文件或 Docker CLI 状态。

## 未执行的健康检查与连通性

当前 Docker 阻塞发生在构建阶段，尚无运行中的服务实例。因此以下验证仍未执行：

- `racs-api`：`http://localhost:8000/health/live`
- `mock-business-api`：`http://localhost:8001/health/live`
- `postgres`：`pg_isready -U $POSTGRES_USER -d $POSTGRES_DB`
- `web`：`http://localhost:5173` 访问及其到 API 的连通性。

## 关闭条件

在已验证 Docker BuildKit 可用的受控发布环境中，使用未修改的项目文件执行并保存完整输出：

```powershell
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml up --build -d
docker compose -f deploy/compose.yaml ps
```

确认全部容器健康、两个 API 健康接口可用、PostgreSQL 健康、Web 可访问且必要 API 连通后，执行：

```powershell
docker compose -f deploy/compose.yaml down
docker compose -f deploy/compose.yaml ps
```

之后仍需取得项目所有者明确的 `v1.0.0` 发布授权；在此之前不得升版、创建 Tag、推送或发布。
