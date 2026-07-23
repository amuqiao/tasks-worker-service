# Worker Runtime

本文记录 `fastapi-lite` 当前 Worker runtime 的运行入口、配置和 broker ack 语义。业务 task 模板、幂等、input_ref/output_ref 和长任务写法见 [`worker-template.md`](worker-template.md)。

## Runtime Boundary

Worker Service 只执行本仓库注册的 handler，并通过 Job Service Worker Internal HTTP API 改变 Job 生命周期。

```text
taskiq Redis Stream
  -> app.job_platform_worker.runner
  -> app.job_platform_worker.runtime
  -> Worker Manifest handler
  -> tasks-platform Worker Internal API
```

`taskiq` 在当前实现中只负责接收 `QueueEnvelope` 消息；Job 状态权威仍在 `tasks-platform`。

## Entry Points

| 入口 | 当前职责 |
|---|---|
| `start-worker.sh` | Worker Pod/容器入口，执行 `python -m app.job_platform_worker.runner`。 |
| `app.job_platform_worker.runner` | 直接监听 `RedisStreamBroker.listen()`，按 runtime 返回值显式调用或跳过 `message.ack()`。 |
| `app.job_platform_worker.taskiq_app` | 创建 Redis Stream broker；不注册默认 `taskiq worker` 消费入口。 |
| `app.job_platform_worker.taskiq_tasks` | 提供 `run_queue_envelope_with_settings()` composition helper，不注册默认 `taskiq worker` 消费入口。 |
| `app.job_platform_worker.runtime` | 校验 `QueueEnvelope`、acquire、heartbeat、执行 handler、complete/fail，并返回 `ack` 或 `no_ack`。 |
| `app.job_platform_worker.manifest` | 读取 `worker.manifest.json`，校验任务声明并按 handler path 构建 registry。 |
| `app.job_platform_worker.registry` | 从 manifest 构建 handler registry，不手写业务 task 注册。 |
| `app.job_platform_worker.register_cli` | 提供 `validate` / `render` / `register`，用于本地和 CI/CD 注册 Worker Manifest。 |
| `app.worker.task_modules.example.handler` | 示例业务 handler。 |

当前唯一支持的生产消费路径是 `python -m app.job_platform_worker.runner`，因为该入口直接控制 broker message ack。不要使用默认 `taskiq worker` 启动本服务的 Worker 消费进程。

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
WORKER__JOB_SERVICE_API_KEY=dev-worker-key
WORKER__JOB_SERVICE_REGISTRY_API_KEY=dev-registry-api-key
WORKER__MANIFEST_PATH=app/worker/manifest.json
```

`WORKER__JOB_SERVICE_API_KEY` 只用于 Worker runtime 调用 Job Service Worker Internal API；`WORKER__JOB_SERVICE_REGISTRY_API_KEY` 只用于 CI/CD 或人工运维注册 Worker Manifest。`TASKIQ__QUEUE_NAME` 必须与 Job Service 发布的 `QueueEnvelope.queue_name` 一致，Worker 启动和 `register_cli validate|render|register` 都会校验它与 manifest `queue_name` 一致。`redis_list` broker 不支持当前链路。

## Ack Semantics

Worker runtime 返回值与 broker 行为：

| runtime 结果 | broker 行为 | 当前含义 |
|---|---|---|
| `ack` | 调用 `message.ack()` | 消息已完成、已安全忽略，或是 poison message。 |
| `no_ack` | 不调用 `message.ack()` | Job Service 状态未知、lease 状态未知、complete/fail 结果未知，消息保留给 broker pending/reclaim。 |

真实 Redis Stream gate 会验证：

- ack 后 consumer group pending count 回到 `0`。
- 未 ack 的消息进入 pending，并可由另一个 consumer 通过 taskiq-redis reclaim 再次取得。

## Worker Manifest

正式任务接入只通过 Worker Manifest。业务 handler 不在 `app.job_platform_worker.registry` 中手写注册。

```json
{
  "manifest_version": 1,
  "worker_service": "worker-x",
  "queue_name": "job.example-task.v1",
  "capabilities": ["cpu"],
  "tasks": [
    {
      "task_name": "example.task",
      "task_version": 1,
      "handler": "app.worker.task_modules.example.handler:ExampleTaskHandler",
      "input_schema": {"type": "object", "additionalProperties": true},
      "output_schema": {"type": "object", "additionalProperties": true},
      "caller_bindings": [
        {"caller_service": "business-api-a", "compensation_window_seconds": 3600}
      ]
    }
  ]
}
```

Worker 启动时使用同一份 manifest import handler 并注册到本地 `HandlerRegistry`。CI/CD 或人工运维通过同一份 manifest 调用 Job Service Registry API，使 Job Service 保存 task/schema/queue/binding。新增业务 task 时不修改 Job Service 代码，也不修改 `app.job_platform_worker.registry`。同一 task/version 的 schema、runtime policy 和 binding 不做静默更新；变化应升版本或走显式迁移。

本地校验：

```bash
uv run python -m app.job_platform_worker.register_cli validate
```

渲染将发送给 Job Service 的 payload：

```bash
uv run python -m app.job_platform_worker.register_cli render
```

注册到 Job Service：

```bash
uv run python -m app.job_platform_worker.register_cli register
```

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
