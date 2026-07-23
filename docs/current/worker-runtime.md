# Worker Runtime

本文记录 `fastapi-lite` 当前 Worker runtime 的运行入口、配置和 broker ack 语义。未来业务 handler、执行表和业务侧幂等设计不写入本文。

## Runtime Boundary

Worker Service 只执行本仓库注册的 handler，并通过 Job Service Worker Internal HTTP API 改变 Job 生命周期。

```text
taskiq Redis Stream
  -> app.worker.runner
  -> app.worker.runtime
  -> app.worker.task_modules.*
  -> tasks-platform Worker Internal API
```

`taskiq` 在当前实现中只负责接收 `QueueEnvelope` 消息；Job 状态权威仍在 `tasks-platform`。

## Entry Points

| 入口 | 当前职责 |
|---|---|
| `start-worker.sh` | Worker Pod/容器入口，执行 `python -m app.worker.runner`。 |
| `app.worker.runner` | 直接监听 `RedisStreamBroker.listen()`，按 runtime 返回值显式调用或跳过 `message.ack()`。 |
| `app.worker.taskiq_app` | 创建 Redis Stream broker，并注册 taskiq task。 |
| `app.worker.taskiq_tasks` | 提供 `run_queue_envelope_with_settings()` composition helper，不注册默认 `taskiq worker` 消费入口。 |
| `app.worker.runtime` | 校验 `QueueEnvelope`、acquire、heartbeat、执行 handler、complete/fail，并返回 `ack` 或 `no_ack`。 |
| `app.worker.registry` | 构建 handler registry。 |
| `app.worker.task_modules.example` | 示例业务 handler 注册模板。 |

当前唯一支持的生产消费路径是 `python -m app.worker.runner`，因为该入口直接控制 broker message ack。不要使用默认 `taskiq worker` 启动本服务的 Worker 消费进程。

## Required Configuration

Worker 与 Job Service 对接时至少需要：

```dotenv
TASKIQ__BROKER_KIND=redis_stream
TASKIQ__REDIS_URL=redis://127.0.0.1:6379/0
TASKIQ__QUEUE_NAME=job.example-task.v1
TASKIQ__TASK_NAME=job-platform.consume_queue_envelope
WORKER__JOB_SERVICE_BASE_URL=http://127.0.0.1:8100/internal/v1
WORKER__SERVICE_NAME=example-worker
WORKER__WORKER_NAME=example-worker-taskiq
WORKER__WORKER_SESSION_ID=example-worker-local
WORKER__JOB_SERVICE_API_KEY=dev-service-api-key
```

`TASKIQ__QUEUE_NAME` 必须与 Job Service 发布的 `QueueEnvelope.queue_name` 一致。`redis_list` broker 不支持当前链路。

## Ack Semantics

Worker runtime 返回值与 broker 行为：

| runtime 结果 | broker 行为 | 当前含义 |
|---|---|---|
| `ack` | 调用 `message.ack()` | 消息已完成、已安全忽略，或是 poison message。 |
| `no_ack` | 不调用 `message.ack()` | Job Service 状态未知、lease 状态未知、complete/fail 结果未知，消息保留给 broker pending/reclaim。 |

真实 Redis Stream gate 会验证：

- ack 后 consumer group pending count 回到 `0`。
- 未 ack 的消息进入 pending，并可由另一个 consumer 通过 taskiq-redis reclaim 再次取得。

## Handler Template

业务 handler 通过注册模块接入：

```text
app/worker/task_modules/<business_module>.py
  def register_handlers(registry: HandlerRegistry) -> None
```

当前默认 registry 在 `app.worker.registry.build_worker_registry()` 中注册 `example.task@v1`。后续接入具体业务时，新增 task module 并在 `build_worker_registry()` 中显式调用注册函数；不修改 `app.worker.runner`、`app.worker.runtime` 或 `app.worker.taskiq_app`。

## Verification

默认验证：

```bash
./scripts/verify.sh check
```

真实 Redis Stream broker gate 需要显式 Redis URL：

```bash
FASTAPI_LITE_REDIS_STREAM_URL=redis://127.0.0.1:6379/0 ./scripts/verify.sh redis-stream
```

该 gate 会创建并删除测试专用 stream 和 consumer group，不启动或停止 Redis。
