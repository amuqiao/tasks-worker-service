# Current Implementation

本文记录 `fastapi-lite` 当前已经实现并由测试覆盖的工程事实。它不描述未来计划；未实现内容见 [`../plans/drift-checklist.md`](../plans/drift-checklist.md)。

## Runtime Model

`fastapi-lite` 当前按三层组织：

```text
foundation
  -> config / logging / request context / error envelope / registries / scripts
integrations
  -> Postgres lifecycle / Redis fake boundary / object storage / shared HTTP client
example domain
  -> items route / schema / service / repository / ORM model / migration
```

FastAPI app 由 `app.main.create_app()` 创建。`lifespan` 在启动期构建 health registry 和 lifecycle provider registry，按顺序启动 provider，注册 readiness checks，并在启动后冻结 registry；关闭时按反序释放资源。

## HTTP Foundation

已实现的 HTTP 基础能力：

- `/health` 返回进程存活状态。
- `/ready` 聚合 `process`、`postgres`、`redis`、`object_storage`、`http_client` checks。
- 响应统一使用 success/error envelope。
- `X-Request-ID` 和 `X-Trace-ID` 会被生成、校验、透传并写回响应 header。
- `RequestValidationError` 映射为 `REQUEST_INVALID`。
- `AppError` 通过 error registry 映射为注册错误码。
- 未捕获异常映射为 `INTERNAL_ERROR`，响应不暴露内部异常细节。
- operation registry 记录 method、path、operation id、成功状态码、route-specific 业务错误码和 schema 名称。当前 drift check 会校验 method、path、operation id 和成功状态码；错误码和 schema 名称由 registry metadata 与文档约束维护。

## Configuration

配置使用 `app/core/config/` 的 section 化模型：

- `RuntimeSettings`
- `ServiceSettings`
- `SecuritySettings`
- `DatabaseSettings`
- `RedisSettings`
- `StorageSettings`
- `HttpClientSettings`
- `ObservabilitySettings`

`AppSettings` 只聚合 section 并执行跨 section 校验。`env_manifest.py` 是 `.env.example` key 的可执行清单，`scripts/verify/env_config_check.py` 会校验 example key、未知 key、废弃 key、派生 key 和 release profile 约束。

## Database And Items Example

当前数据库层使用 SQLAlchemy async 和 Alembic：

```text
route
  -> service
  -> UnitOfWork
  -> repository
  -> ORM model
  -> migration
```

`items` 示例模块已经实现：

- `POST /v1/items`
- `GET /v1/items/{item_id}`
- `GET /v1/items`
- `PATCH /v1/items/{item_id}`
- `DELETE /v1/items/{item_id}`

`items` 使用 soft delete、乐观并发 `version`、活动记录部分唯一约束、cursor pagination 和 repository mutation result。普通测试使用 SQLite in-memory session override；PostgreSQL integration 测试必须显式通过 `./scripts/verify.sh postgres` 启用，并由 `_test` 数据库保护。

## Providers

当前 lifecycle providers：

| Provider | 当前实现 | Ready 语义 |
|---|---|---|
| `postgres` | app lifespan 内创建 async engine 和 session factory；测试可显式覆盖 session factory。 | 非 override 场景必须是 PostgreSQL URL，并执行 `SELECT 1`。 |
| `redis` | fake client；`REDIS__ENABLED=true` 会显式失败。 | fake client 未关闭则 ok。 |
| `object_storage` | `disabled` backend 和 local filesystem backend。 | provider 成功启动则 ok。 |
| `http_client` | shared `httpx.AsyncClient`，注入 request/trace headers。 | client 未关闭则 ok。 |

业务请求路径通过 typed dependency 从 `request.app.state` 获取资源，不通过 lifecycle registry 字符串查找，也不依赖模块级数据库懒初始化。

## Tools

`app/tools/example_tool.py` 提供一个纯函数工具示例：

- `ToolSpec` metadata。
- `ExampleToolInput` / `ExampleToolOutput` schema。
- `slugify_text()` callable。
- `validate_example_tool_spec()` drift check。

首版工具模块不做运行时动态发现和动态执行。

## Scripts And Verification

可用入口：

- `./scripts/dev.sh help`
- `./scripts/dev.sh doctor`
- `./scripts/dev.sh ports`
- `./scripts/dev.sh migrate`
- `./scripts/deploy.sh help`
- `./scripts/deploy.sh up|down|status local`
- `./scripts/deploy.sh up|down|status compose-deps`
- `./scripts/deploy.sh up|down|status compose-full`
- `./scripts/verify.sh check`
- `./scripts/verify.sh postgres`
- `./scripts/verify.sh migration-roundtrip`
- `./scripts/tools.sh secret`
- `./scripts/tools.sh env-url`

`dev.sh` 当前提供本地 API 进程管理、端口扫描、环境检查、迁移和测试快捷入口。`deploy.sh` 当前提供三种基础部署模型：`local` 委托 `dev.sh`，`compose-deps` 管理 PostgreSQL / Redis，`compose-full` 管理 API / PostgreSQL / Redis，并通过 `start-api.sh` 作为 API 容器入口。`verify.sh check` 当前覆盖 env、syntax、registry、alembic、scripts 和 pytest；`postgres` 与 `migration-roundtrip` 是显式 PostgreSQL gate。`tools.sh` 当前提供无默认持久副作用的 secret 和 env URL 生成工具。

## Verification Baseline

当前验收命令：

```bash
./scripts/verify.sh check
./scripts/deploy.sh check
```

PostgreSQL 集成测试和 migration roundtrip 是显式 gate：

```bash
./scripts/verify.sh postgres
./scripts/verify.sh migration-roundtrip
```
