# Scripts

`scripts/` 是 `tasks-worker-service` 的稳定本地操作入口。脚本遵循“入口合同清晰、输出可判定、高风险显式、错误快速暴露”的规则。

## Entrypoints

| Entry | Scope |
|---|---|
| `dev.sh` | 本地开发：bootstrap、doctor、端口扫描、API / Worker 生命周期、迁移和测试快捷入口。 |
| `verify.sh` | 一次性验证：env、syntax、registry、Alembic、脚本 smoke、pytest、PostgreSQL integration gate、Redis Stream gate、migration roundtrip gate、可选 Job Platform smoke。 |
| `deploy.sh` | 运行模型入口：dev、dev-worker、local、worker、compose-deps、compose-worker、compose-full；`down all` 显式全量停止。 |
| `k8s.sh` | K8s Pod 内运维：配置、PostgreSQL、应用健康、Alembic 状态和手动迁移检查。 |
| `smoke-job-platform.sh` | 跨仓 smoke：当前 Worker 模板注册到本地 `tasks-platform`，提交 job，dispatch，并等待 worker complete。 |
| `tools.sh` | 无默认持久副作用工具：secret 生成、DATABASE__URL / REDIS__URL 编码。 |

## Shared Helpers

| File | Responsibility |
|---|---|
| `lib/common.sh` | 根目录定位、稳定输出 helper、错误退出、env 读取、前置条件检查。 |
| `lib/runtime.sh` | 本地 API host/port/url、PID/log 路径、端口和进程 helper。 |
| `lib/compose.sh` | docker compose / docker-compose 适配、compose project name 派生和 env 注入。 |
| `lib/modes.sh` | local/compose 运行模式互斥保护、worker/deps 停启保护、compose project 冲突检查。 |
| `dev/check_ports.py` | 本地 TCP 端口扫描，支持人读输出和 JSON 输出。 |
| `tools/env_url.py` | 生成编码后的 PostgreSQL / Redis URL。 |
| `verify/migration_roundtrip.py` | 临时本地 PostgreSQL migration roundtrip 检查。 |

## Contract Rules

- 所有顶层入口必须支持 `help` / `-h` / `--help`。
- 未知命令返回 exit code `2`。
- 默认输出面向人读；机器读输出只在明确支持的命令中使用，例如 `dev.sh ports --json`。
- 写入、启动进程、迁移数据库等副作用必须在 help 中说明。
- 脚本不读取隐藏配置源；默认配置文件是仓库根目录 `.env`，可用 `ENV_FILE` 覆盖。

## Service Management Ways

| Way | Commands | Scope |
|---|---|---|
| 日常入口 | `./scripts/deploy.sh up/status/down dev` | Docker PostgreSQL / Redis + 宿主机 API。`dev` 不自动启动 Worker。 |
| 单进程入口 | `./scripts/dev.sh start/status/stop api|worker` | 只管理宿主机 API 或 Worker 进程，不启动或停止 Docker 依赖。 |
| 运行模型入口 | `./scripts/deploy.sh up/status/down worker|dev-worker|compose-deps|compose-worker|compose-full` | 显式选择 Worker、依赖、Compose Worker 或全 Compose API 模型。 |

## Common Commands

```bash
./scripts/dev.sh doctor
./scripts/dev.sh ports 8130 25435 26382
./scripts/deploy.sh up dev
./scripts/deploy.sh status dev
./scripts/deploy.sh down dev
./scripts/dev.sh start api
./scripts/dev.sh status api
./scripts/dev.sh stop api
./scripts/dev.sh start worker
./scripts/dev.sh status worker
./scripts/dev.sh stop worker
./scripts/deploy.sh up worker
./scripts/deploy.sh status worker
./scripts/deploy.sh down worker
./scripts/deploy.sh up dev-worker
./scripts/deploy.sh status dev-worker
./scripts/deploy.sh down dev-worker
./scripts/deploy.sh up compose-deps
./scripts/deploy.sh status compose-deps
./scripts/deploy.sh down compose-deps
./scripts/deploy.sh up compose-worker
./scripts/deploy.sh status compose-worker
./scripts/deploy.sh down compose-worker
./scripts/deploy.sh up compose-full
./scripts/deploy.sh status compose-full
./scripts/deploy.sh down all
./scripts/tools.sh secret
./scripts/verify.sh check
./scripts/smoke-job-platform.sh check
./scripts/deploy.sh check
kubectl exec -it <api-pod> -- ./scripts/k8s.sh check
```
