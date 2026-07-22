# Scripts

`scripts/` 是 `fastapi-lite` 的稳定本地操作入口。脚本遵循“入口合同清晰、输出可判定、高风险显式、错误快速暴露”的规则。

## Entrypoints

| Entry | Scope |
|---|---|
| `dev.sh` | 本地开发：bootstrap、doctor、端口扫描、API 生命周期、迁移和测试快捷入口。 |
| `verify.sh` | 一次性验证：env、syntax、registry、Alembic、脚本 smoke、pytest、PostgreSQL integration gate、migration roundtrip gate。 |
| `deploy.sh` | 三模式部署入口：local、compose-deps、compose-full。 |
| `k8s.sh` | K8s Pod 内运维：配置、PostgreSQL、应用健康、Alembic 状态和手动迁移检查。 |
| `tools.sh` | 无默认持久副作用工具：secret 生成、DATABASE__URL / REDIS__URL 编码。 |

## Shared Helpers

| File | Responsibility |
|---|---|
| `lib/common.sh` | 根目录定位、稳定输出 helper、错误退出、env 读取、前置条件检查。 |
| `lib/runtime.sh` | 本地 API host/port/url、PID/log 路径、端口和进程 helper。 |
| `lib/compose.sh` | docker compose / docker-compose 适配、compose project name 派生和 env 注入。 |
| `lib/modes.sh` | local 与 compose-full 互斥保护、compose project 冲突检查。 |
| `dev/check_ports.py` | 本地 TCP 端口扫描，支持人读输出和 JSON 输出。 |
| `tools/env_url.py` | 生成编码后的 PostgreSQL / Redis URL。 |
| `verify/migration_roundtrip.py` | 临时本地 PostgreSQL migration roundtrip 检查。 |

## Contract Rules

- 所有顶层入口必须支持 `help` / `-h` / `--help`。
- 未知命令返回 exit code `2`。
- 默认输出面向人读；机器读输出只在明确支持的命令中使用，例如 `dev.sh ports --json`。
- 写入、启动进程、迁移数据库等副作用必须在 help 中说明。
- 脚本不读取隐藏配置源；默认配置文件是仓库根目录 `.env`，可用 `ENV_FILE` 覆盖。

## Common Commands

```bash
./scripts/dev.sh doctor
./scripts/dev.sh ports 8100 25432 26379
./scripts/dev.sh start api
./scripts/deploy.sh up compose-deps
./scripts/deploy.sh up compose-full
./scripts/tools.sh secret
./scripts/verify.sh check
./scripts/deploy.sh check
kubectl exec -it <api-pod> -- ./scripts/k8s.sh check
```
