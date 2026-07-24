# Current Implementation

本文记录 `tasks-worker-service` 当前已经实现并由测试覆盖的工程事实。它不描述未来计划；模板使用入口见 [`../README.md`](../README.md)。

## Runtime Model

`tasks-worker-service` 当前按三层组织：

```text
foundation
  -> config / logging / request context / error envelope / registries / scripts
integrations
  -> Postgres lifecycle / Redis fake boundary / object storage / shared HTTP client
example domain
  -> items route / schema / service / repository / ORM model / migration
worker runtime
  -> Job Platform QueueEnvelope DTOs / Worker HTTP client / handler registry / taskiq consumer
```

FastAPI app 由 `app.main.create_app()` 创建。`lifespan` 在启动期构建 health registry 和 lifecycle provider registry，按顺序启动 provider，注册 readiness checks，并在启动后冻结 registry；关闭时按反序释放资源。

## HTTP Foundation

已实现的 HTTP 基础能力：

- `/health` 返回进程存活状态。
- `/ready` 聚合 `process`、`postgres`、`redis`、`object_storage`、`http_client` checks。
- 响应统一使用 success/error envelope。
- `X-Request-ID` 和 `X-Trace-ID` 会被生成、校验、透传并写回响应 header。
- `RequestContextMiddleware` 负责 request/trace header 校验、context 注入、响应 header 回写和 access log。`create_app()` 显式安装 `RequestContextMiddleware` 和 `CORSMiddleware`。
- `RequestValidationError` 映射为 `REQUEST_INVALID`。
- `AppError` 通过 error registry 映射为注册错误码。
- 未捕获异常映射为 `INTERNAL_ERROR`，响应不暴露内部异常细节。
- access log、`AppError` log 和未捕获异常 log 都带稳定字段：`request_id`、`trace_id`、`method`、`path`、`operation_id`、`status`、`duration_ms`、`error_code`。
- operation registry 记录 method、未挂载 path、operation id、成功状态码、auth 要求、route-specific 业务错误码和 schema 名称。业务 route 的公开路径由 `SERVICE__API_PREFIX` 渲染，避免在 registry、router 和文档中重复硬编码 `/v1`。
- registry drift check 会校验 route method/path/operation id/成功状态码、OpenAPI request schema、OpenAPI error response、OpenAPI security、已注册错误码，以及 `docs/contracts/api-contract.md` 的 Routes 表关键字段。

## Configuration

配置使用 `app/core/config/` 的 section 化模型：

- `RuntimeSettings`
- `ServiceSettings`
- `SecuritySettings`
- `DatabaseSettings`
- `RedisSettings`
- `TaskiqSettings`
- `WorkerSettings`
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

`app.models` 是 ORM metadata 的显式注册入口。Alembic env、SQLite 测试建表和 migration roundtrip 都通过导入 `app.models` 触发已注册模型加载，再使用 `Base.metadata` 作为表集合来源。`scripts/verify/migration_roundtrip.py` 的 head schema 断言按 registered metadata 表集合校验，不硬编码 `items`。

`UnitOfWork` 必须显式接收 `session_factory`，业务 service 必须由 route、worker 或测试这样的 composition root 注入 `UowFactory`。HTTP route 从 `request.app.state.db_session_factory` 构造 `UowFactory`，避免 service 或 repository 隐式依赖进程级全局数据库状态。

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

## Worker Runtime

当前仓库已经包含面向 Job Platform 的 Worker runtime 模板：

- `app/job_platform_worker/protocol.py` 定义本服务消费 Job Platform `QueueEnvelope` 和 Worker Internal API 所需 DTO。
- `app/job_platform_worker/job_client.py` 通过 `Bearer worker:<worker_service>:<WORKER_API_KEY>` 调用 Job Service `/internal/v1/attempts/{attempt_id}/acquire|complete|fail`。
- `app/job_platform_worker/runtime.py` 负责 envelope 校验、handler 查找、acquire、业务 handler 执行期间 heartbeat、complete/fail 回写和 `ack/no_ack` 决策。
- `app/job_platform_worker/handlers.py` 提供 `HandlerRegistry`、`TaskHandler` 和兼容的 `build_default_registry()` 入口。
- `app/job_platform_worker/manifest.py` 负责读取和校验 Worker Manifest；`app/worker/manifest.json` 是当前 worker 的正式任务声明源；`app/job_platform_worker/registry.py` 只从 manifest 构建 handler registry，不手写业务 task 注册。
- `app/job_platform_worker/register_cli.py` 提供 `validate` / `render` / `register`，用于本地和 CI/CD 把 Worker Manifest 注册到 Job Service；注册使用独立 `WORKER__JOB_SERVICE_REGISTRY_API_KEY`，不复用 Worker runtime token。
- `app/job_platform_worker/taskiq_app.py` 创建 Redis Stream broker；`app/job_platform_worker/taskiq_tasks.py` 提供 runtime composition helper，不注册默认 `taskiq worker` 消费入口。
- `app/job_platform_worker/runner.py` 直接使用 taskiq Redis Stream broker `listen()`，只在 runtime 返回 `ack` 时调用 broker message `ack()`；`no_ack` 不会走默认 `taskiq worker` 的隐式 ack 路径。
- `TASKIQ__QUEUE_NAME` 是 Worker 监听的物理 Redis Stream，必须与 manifest `queue_name` 和 Job Service 发布的 `QueueEnvelope.queue_name` 匹配；CLI 和 runtime 都会 fail fast 校验；`redis_list` broker 不支持该链路。
- `start-worker.sh` 是 Worker Pod 入口；`docker-compose.yml` 的 `worker` profile 可构建容器化 worker，不影响现有 API profile。
- `scripts/smoke-job-platform.sh` 是可选跨仓 smoke 入口，使用当前 Worker manifest 注册到本地 `tasks-platform`，提交 job，调用 Job Service dispatcher，并等待当前 Worker runner complete。

Worker runtime 的运行入口、配置和 ack/no_ack broker 语义记录在 [`worker-runtime.md`](worker-runtime.md)。作为可复制模板新增业务 task 的目录、manifest、幂等、input_ref/output_ref 和长任务规范记录在 [`worker-template.md`](worker-template.md)。

## Scripts And Verification

可用入口：

- `./scripts/dev.sh help`
- `./scripts/dev.sh doctor`
- `./scripts/dev.sh ports`
- `./scripts/dev.sh migrate`
- `./scripts/deploy.sh help`
- `./scripts/deploy.sh up|down|status dev`
- `./scripts/deploy.sh up|down|status dev-worker`
- `./scripts/deploy.sh up|down|status local`
- `./scripts/deploy.sh up|down|status worker`
- `./scripts/deploy.sh up|down|status compose-deps`
- `./scripts/deploy.sh up|down|status compose-worker`
- `./scripts/deploy.sh up|down|status compose-full`
- `./start-worker.sh`
- `./scripts/verify.sh check`
- `./scripts/verify.sh postgres`
- `./scripts/verify.sh redis-stream`
- `./scripts/verify.sh job-platform-smoke`
- `./scripts/verify.sh migration-roundtrip`
- `./scripts/smoke-job-platform.sh check|run`
- `./scripts/tools.sh secret`
- `./scripts/tools.sh env-url`

`dev.sh` 当前提供本地 API / Worker 进程管理、端口扫描、环境检查、迁移和测试快捷入口。`deploy.sh` 当前提供七种基础部署模型：`dev` 组合 `compose-deps + local`，`dev-worker` 组合 `compose-deps + local + worker`，`local` 委托 `dev.sh start|stop|status api`，`worker` 委托 `dev.sh start|stop|status worker`，`compose-deps` 管理 PostgreSQL / Redis，`compose-worker` 管理 Docker Worker 和本仓库 PostgreSQL / Redis，并预检外部 Job Redis broker，`compose-full` 管理 API / PostgreSQL / Redis，并通过 `start-api.sh` 作为 API 容器入口；worker profile 使用 `start-worker.sh` 作为 Worker 容器入口。`verify.sh check` 当前覆盖 env、syntax、registry、alembic、scripts 和 pytest；`postgres` 与 `migration-roundtrip` 是显式 PostgreSQL gate，`redis-stream` 是显式 Redis Stream broker gate，`job-platform-smoke` 是显式跨仓 Job Service gate。`tools.sh` 当前提供无默认持久副作用的 secret 和 env URL 生成工具。

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
FASTAPI_LITE_REDIS_STREAM_URL=redis://127.0.0.1:26382/0 ./scripts/verify.sh redis-stream
```

跨仓 Job Service smoke 是显式 gate：

```bash
./scripts/smoke-job-platform.sh check
./scripts/verify.sh job-platform-smoke
```
