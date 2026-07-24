# Worker Service Docs

本文是 `tasks-worker-service` 模板文档入口。模板使用者优先阅读 current 文档；contracts 只描述对外可依赖的 HTTP 和扩展边界。

## 三端接入阅读链路

新业务开发不要只按单仓阅读。推荐顺序是：

```text
tasks-platform/docs/notes/business_job_worker心智模型.md
  -> tasks-business-api/docs/current/business-example-config.md
  -> tasks-worker-service/docs/current/worker-example-config.md
  -> tasks-business-api/docs/current/business-template.md
  -> tasks-worker-service/docs/current/worker-template.md
  -> tasks-business-api ./scripts/three-service-flow.sh lifecycle
```

当前仓库负责其中的 Worker identity、queue、manifest、runner 和 handler 入口。Business submit、callback 和 query/polling 需要先对齐业务仓库的 [`business-example-config.md`](../../tasks-business-api/docs/current/business-example-config.md)。

## 模板开发入口

- [`current/worker-example-config.md`](current/worker-example-config.md)：新业务接入前的示例配置入口。先确认 worker identity、queue、manifest、token 和 Business caller 如何对齐。
- [`current/worker-template.md`](current/worker-template.md)：新增业务 worker task 的主要手册。复制模板后，业务开发按这篇进入具体目录。
- [`current/worker-runtime.md`](current/worker-runtime.md)：worker runner、attempt、ack/no_ack、heartbeat、cancel 的当前运行模型。
- [`current/implementation.md`](current/implementation.md)：仓库当前实现事实和脚本能力总览。

## 稳定合同

- [`contracts/api-contract.md`](contracts/api-contract.md)：HTTP API 合同。
- [`contracts/extension-contract.md`](contracts/extension-contract.md)：扩展仓库骨架、脚本和 provider 时的工程合同。

## 模板边界

新业务 worker task 默认只在以下位置扩展：

```text
app/worker/manifest.json
app/worker/task_modules/<business_task>/
```

通常不要修改：

```text
app/job_platform_worker/
```

`app/job_platform_worker/` 是 Job Platform 对接层；业务 task 通过 manifest 和 handler 接入，不直接改 runtime、runner、Job client 或 broker adapter。
