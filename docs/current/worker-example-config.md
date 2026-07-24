# Worker Example Configuration

本文是三端新业务接入链路的第 3 步：读完心智模型和 Business 示例配置后，阅读本文确认 Worker 服务如何声明 task、如何连接 Job Service、如何消费队列。本文之后，再进入 [`worker-template.md`](worker-template.md) 和业务仓库的 [`business-template.md`](../../../tasks-business-api/docs/current/business-template.md) 开发具体 handler 与业务投影。

本文只说明当前模板已经实现的配置和 manifest 形状，不讲 runner/runtime 源码细节。

## 先理解 Worker 这一端

Worker 服务在三端链路里负责：

```text
Worker manifest
  -> 注册 task capability 到 Job Service
  -> runner 消费 Redis Stream QueueEnvelope
  -> acquire attempt
  -> 调业务 handler
  -> complete / fail / cancel 回写 Job Service
```

Worker 不直接调用 Business，也不投递 callback。Business 的终态更新由 Job Service callback 完成。

## 最小本地配置

在 `tasks-worker-service` 仓库根目录 `.env` 中，Worker 与 Job Service 对接相关配置长这样：

```dotenv
WORKER__SERVICE_NAME=worker-x
WORKER__WORKER_NAME=worker-x-taskiq
WORKER__WORKER_SESSION_ID=worker-x-local
WORKER__JOB_SERVICE_BASE_URL=http://127.0.0.1:8110/internal/v1
WORKER__JOB_SERVICE_API_KEY=dev-worker-key
WORKER__JOB_SERVICE_REGISTRY_API_KEY=dev-registry-key
WORKER__MANIFEST_PATH=app/worker/manifest.json

TASKIQ__BROKER_KIND=redis_stream
TASKIQ__REDIS_URL=redis://127.0.0.1:26380/0
TASKIQ__QUEUE_NAME=job.example-task.v1
```

这些字段的对应关系是：

| 配置 | 含义 | 必须对齐 |
|---|---|---|
| `WORKER__SERVICE_NAME` | Worker 服务身份。 | `manifest.worker_service` 和 Job Service worker token 配置。 |
| `WORKER__WORKER_NAME` | 当前 runner 名称。 | 用于 worker session 识别和排查。 |
| `WORKER__WORKER_SESSION_ID` | 当前 runner session。 | 本地 flow 会用它防止复用旧 runner。 |
| `WORKER__JOB_SERVICE_BASE_URL` | Job Service Worker Internal API 地址。 | `tasks-platform` 当前运行地址，路径包含 `/internal/v1`。 |
| `WORKER__JOB_SERVICE_API_KEY` | runtime token。 | Job Service 的 worker API key 配置。 |
| `WORKER__JOB_SERVICE_REGISTRY_API_KEY` | manifest 注册 token。 | Job Service 的 registry admin key 配置。 |
| `WORKER__MANIFEST_PATH` | 本地 manifest 文件。 | 默认 `app/worker/manifest.json`。 |
| `TASKIQ__REDIS_URL` | Redis Stream broker 地址。 | Job Service dispatcher 发布使用的 Redis。 |
| `TASKIQ__QUEUE_NAME` | Worker 消费的队列名。 | `manifest.queue_name`。 |

`WORKER__JOB_SERVICE_API_KEY` 和 `WORKER__JOB_SERVICE_REGISTRY_API_KEY` 是两类 token，不要混用。

## Manifest 示例

新业务最小 manifest 形状：

```json
{
  "manifest_version": 1,
  "worker_service": "worker-x",
  "queue_name": "job.report-export.v1",
  "capabilities": ["cpu"],
  "tasks": [
    {
      "task_name": "report.export_pdf",
      "task_version": 1,
      "handler": "app.worker.task_modules.report_export.handler:ReportExportHandler",
      "input_schema": {
        "type": "object",
        "required": ["report_id", "format"],
        "properties": {
          "report_id": {"type": "string"},
          "format": {"type": "string"}
        },
        "additionalProperties": false
      },
      "output_schema": {
        "type": "object",
        "required": ["result_uri", "page_count"],
        "properties": {
          "result_uri": {"type": "string"},
          "page_count": {"type": "integer"}
        },
        "additionalProperties": false
      },
      "timeout_seconds": 300,
      "max_retries": 1,
      "retry_policy": {},
      "idempotency_retention_seconds": 86400,
      "required_worker_capabilities": ["cpu"],
      "caller_bindings": [
        {
          "caller_service": "tasks-business-api",
          "callback_url": null,
          "compensation_window_seconds": 3600
        }
      ]
    }
  ]
}
```

必须保持：

```text
manifest.worker_service == WORKER__SERVICE_NAME
manifest.queue_name == TASKIQ__QUEUE_NAME
tasks[].caller_bindings[].caller_service == Business 的 JOB_SERVICE__CALLER_SERVICE
```

`callback_url` 在当前新业务接入里通常保持 `null`。Business submit job 时会携带自己的 callback URL、key id 和 secret ref，Job Service 终态后按 submit 冻结的 callback 配置投递。

## Handler 示例

业务 handler 只做适配，不重新实现 Job 生命周期：

```text
QueueEnvelope.input
  -> 业务 input schema
  -> task service 执行业务逻辑
  -> HandlerResult(output=...)
  -> runtime 调 Job Service complete/fail/cancel
```

最小目录：

```text
app/worker/task_modules/report_export/
  __init__.py
  schemas.py
  service.py
  handler.py
```

伪代码形状：

```text
ReportExportHandler.handle(envelope, context):
  input = validate(envelope.input)
  result = report_export_service.export(input.report_id, input.format)
  return HandlerResult(output={result_uri, page_count})
```

真正代码范式看 [`worker-template.md`](worker-template.md)。业务逻辑放在 task module 内，不要修改 `app/job_platform_worker/`。

## 注册和运行顺序

本地开发顺序：

```bash
uv run python -m app.job_platform_worker.register_cli validate
uv run python -m app.job_platform_worker.register_cli render
uv run python -m app.job_platform_worker.register_cli register
python -m app.job_platform_worker.runner
```

也可以使用脚本入口管理本地 worker：

```bash
./scripts/deploy.sh up worker
./scripts/deploy.sh status worker
./scripts/deploy.sh down worker
```

Worker 注册成功后，Business submit 的 `task_name / task_version` 才能被 Job Service 接受。

## 和 Business 配置如何对齐

Worker 和 Business 至少要对齐这几项：

| Worker manifest/config | Business 配置/请求 |
|---|---|
| `caller_bindings[].caller_service=tasks-business-api` | `JOB_SERVICE__CALLER_SERVICE=tasks-business-api` |
| `tasks[].task_name=report.export_pdf` | submit `task_name=report.export_pdf` |
| `tasks[].task_version=1` | submit `task_version=1` |
| `tasks[].input_schema` | submit `input` |
| `tasks[].output_schema` | Business callback 投影 `output` |
| `queue_name=job.report-export.v1` | Job Service dispatch outbox 发布到同名 queue |
| `TASKIQ__REDIS_URL` | Job Service dispatcher 使用同一 Redis broker |

Worker 只关心 Job Service Worker Internal API 和队列，不关心 Business 的数据库、route 或 callback receiver 实现。

## 验证入口

Worker 仓库内先跑：

```bash
uv run python -m app.job_platform_worker.register_cli validate
./scripts/verify.sh check
```

需要单独验证 Worker 与 Job Service 时，可跑：

```bash
./scripts/smoke-job-platform.sh run
```

单仓 smoke 默认使用模板示例 task。真实业务可以只改 smoke 变量，不改脚本：

```dotenv
WORKER_SMOKE_SOURCE_TASK_NAME=report.export_pdf
WORKER_SMOKE_SOURCE_TASK_VERSION=1
WORKER_SMOKE_TASK_NAME=worker_template_smoke.report.export_pdf
WORKER_SMOKE_TASK_VERSION=1
WORKER_SMOKE_INPUT_JSON={"report_id":"report-123","format":"pdf"}
```

这些变量的作用是：

```text
source task
  从 app/worker/manifest.json 里选择真实业务 task。

smoke task
  渲染一个只用于 smoke 的 task_name / task_version，避免污染真实业务 task 注册。

smoke input
  提交给 Job Service 的最小测试输入，必须匹配 source task 的 input_schema。
```

最终三端准入仍在 Business 仓库跑：

```bash
./scripts/three-service-flow.sh lifecycle
```

`lifecycle` 必须真实经过：

```text
Business API submit
  -> Job Service dispatch
  -> Redis Stream
  -> Worker runner
  -> Job Service terminal
  -> callback
  -> Business projection
```


## 本页之后去哪

```text
已完成：Business 示例配置 + Worker 示例配置
下一步：tasks-business-api/docs/current/business-template.md
并行：tasks-worker-service/docs/current/worker-template.md
最后：在 tasks-business-api 仓库根目录运行 ./scripts/three-service-flow.sh lifecycle
```
