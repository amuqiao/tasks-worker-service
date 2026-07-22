# FastAPI Lite 全局心智模型

这是一份精简版全局视角：打开它，只需要快速知道 `fastapi-lite` 的地基有什么、新业务怎么接、哪些能力不要误以为已经有。

## 这是什么

`fastapi-lite` 是一个轻量 FastAPI 服务骨架。

它不追求预置所有功能，而是固定一套基础工程范式：

- HTTP 请求怎么进来。
- 配置、日志、错误码怎么统一。
- 数据库、仓储、迁移怎么组织。
- 外部资源怎么接入生命周期。
- 新业务怎么验证不漂移。

更细的规则看：

- 当前实现：[`../current/implementation.md`](../current/implementation.md)
- 扩展规则：[`../contracts/extension-contract.md`](../contracts/extension-contract.md)
- 后续缺口：[`../plans/drift-checklist.md`](../plans/drift-checklist.md)

## 地基有哪些

- `create_app()`：统一装配 settings、logging、middleware、exception handlers、routers、OpenAPI。
- `lifespan`：统一启动和关闭 provider，并注册 `/ready` 检查。
- 配置管理：section 化 `AppSettings`，配合 env manifest 和 `.env.example` 校验。
- 请求上下文：`X-Request-ID`、`X-Trace-ID` 贯穿响应、日志和下游 HTTP client。
- 日志合同：access/error log 保留 request、trace、method、path、operation、status、duration、error code 等字段。
- 错误合同：`AppError`、error registry、统一 error envelope。
- HTTP 合同：operation registry、OpenAPI、API docs drift check。
- 数据层：SQLAlchemy async、Alembic、`UnitOfWork`、repository。
- 示例业务：`items` CRUD 展示完整业务接口范式。
- Provider：Postgres、Redis fake boundary、object storage、shared HTTP client。
- 工具模块：`app/tools/` 提供纯工具示例。
- 脚本入口：`dev.sh`、`deploy.sh`、`verify.sh`、`tools.sh`。
- 文档分层：`current` 写已实现事实，`contracts` 写稳定合同，`plans` 写后续缺口。

## 关键术语

这些词不是额外概念，而是后续开发时的固定放置点：

- `UnitOfWork`：事务工作单元。一次业务写操作里需要多个 repository 协作时，由它统一提交或回滚。
- `UowFactory`：`UnitOfWork` 的创建入口。service 显式接收它，避免 service 自己创建数据库 session。
- `Repository`：数据访问对象。只负责查询和数据变更，不负责 HTTP、业务编排和事务提交。
- `Provider`：基础设施资源接入单元，例如 PostgreSQL、Redis、OSS、HTTP client。负责启动、挂载、健康检查和关闭。
- `Registry`：注册表。用来集中登记错误码、operation、ORM model 等需要被验证和防漂移检查的对象。
- `lifespan`：FastAPI 生命周期入口。负责按顺序启动 provider、注册 readiness、关闭资源。
- `app.state`：应用级资源挂载点。provider 初始化后的资源放在这里，再通过 typed getter 或 dependency 取用。
- `envelope`：统一响应包裹。成功和失败响应都按固定结构输出，避免接口各自定义格式。

## 新业务怎么接

先分清两个视角：**request 运行时链路** 和 **开发验证链路**。

运行时 request 链路：

```text
request
  -> request_id / trace_id middleware
  -> auth dependency
  -> schema validation
  -> route
  -> service
  -> UowFactory
  -> UnitOfWork
  -> repository
  -> ORM model
  -> database
  -> error mapping
  -> envelope response
```

开发验证链路：

```text
schema
  -> route
  -> operation registry
  -> error registry
  -> service
  -> repository
  -> ORM model
  -> Alembic migration
  -> OpenAPI / docs drift gate
  -> tests
  -> verify
```

核心规则：

- route 只处理 HTTP dependency、status code 和 envelope。
- service 处理事务编排和业务错误映射。
- service 必须显式接收 `UowFactory`，不要自己创建数据库 session。
- repository 只写查询和数据变更，不提交事务。
- ORM model 要登记到 `app/models/__init__.py`。
- 新 route、错误码、API docs 要同步注册。
- 最后跑 `./scripts/verify.sh check`。

## 新基础设施怎么接

新增外部资源按 provider 范式走：

```text
config section
  -> provider startup
  -> app.state resource
  -> health check
  -> readiness
  -> shutdown
  -> tests
```

核心规则：

- 配置先进入 typed settings section。
- provider 在 lifespan 中启动和关闭。
- 资源挂到 `app.state`，业务代码通过 typed getter 或 dependency 使用。
- readiness 要能暴露依赖状态。
- 未实现的真实后端要 fail fast，不要静默降级。

## 当前不要误解

当前骨架不是完整 worker 平台。

这些能力现在不要假设已经可用：

- Celery / Taskiq / Kafka / RabbitMQ。
- broker adapter、outbox、DLQ、reconciler。
- 真实 Redis adapter。
- S3-compatible storage adapter。
- 完整 metrics / rate limit / OpenTelemetry / Prometheus。
- dynamic tool catalog。

这些不是不重要，而是应该等具体业务服务或 worker 服务有真实需求后，再按现有配置、provider、生命周期、测试和文档范式接入。

## 记住一条原则

```text
能复用已有范式就复用；
需要新增范式时，先补合同、示例和验证；
没有真实业务需求时，不提前引入复杂基础设施。
```
