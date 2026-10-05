# A2A 1.2.1 官方最小案例：终态拒绝后的队列清理

2026-10-05，Asia/Shanghai。**官方固定 tag 的 Hello World 执行器已复现，最新 release 与核对的 main 均没有修复此路径。不是 LangGraph、MCP 或业务账本接线引起。** 本轮只读上游、零模型、未改 SDK/site-packages、未发 issue/PR，也未创建 fork。旧协议 probe 和封存证据保持原样。

## 可复验范围与结果

[新脚本](../probes/a2a_official_minimal_repro.py)使用 [v1.2.1 官方 hello_world_agent.py](https://github.com/a2aproject/a2a-python/blob/v1.2.1/samples/hello_world_agent.py) 的原 `SampleAgentExecutor`；[完整源码快照](a2a-official-minimal-source-v1.2.1.py) Git blob 为 `bf38077ddc324f218f3333bd56116665f8eeb1e1`，每次运行先核验。仅抽取未修改的 class AST 执行，以免导入本环境没有的 grpc/FastAPI；保留 SDK executor/updater、InMemoryTaskStore、DefaultRequestHandlerV2、JSONRPC routes 与官方 client，宿主用 Starlette/uvicorn 真实 loopback。删去无关 REST/gRPC/0.3 绑定，增加官方 `handler.aclose()` lifespan。没有导入 LangGraph/MCP/产品业务库。

```powershell
cd D:\Desktop\mihoyo-agent-project
.\research\.venv-protocols\Scripts\python.exe research/probes/a2a_official_minimal_repro.py
```

每次产生独立目录；五种场景分别在新子进程运行。当前 SDK 上整套返回非零，不能当通过测试。最终 [summary.json](a2a-official-minimal-20261005-_409m91j/summary.json) 与各场景 `result.json` / `console.log` 保留完整日志：

| 场景 | dispatcher 实测 | pending 销毁 / OTel detach 告警 | 子进程退出码 |
| --- | --- | --- | --- |
| 三个新 Task，流式 | 全程 0，aclose 后 0 | 0 / 0 | 0 |
| 三个新 Task，非流式 | 全程 0，aclose 后 0 | 0 / 0 | 0 |
| 已完成 Task 追加一次，流式 | 0→2；HTTP client 关闭及 handler.aclose 后仍 2 | 2 / 2 | 2 |
| 已完成 Task 追加一次，非流式 | 0→2；之后自动 GC 回收，aclose 时为 0 | 2 / 2 | 2 |
| 已完成 Task 连续追加五次，流式 | 每次后 2、0、2、4、2；aclose 后 2 | 10 / 10 | 2 |

五种场景的功能检查均成立：官方回复正确、初次任务 COMPLETED、终态重发得到确切 `UnsupportedOperationError`、原 Task 未改变。终态追加是故意发送的非法生命周期请求，SDK 拒绝正确；**正确拒绝不应遗留资源**。在原始官方执行器下仍出错，排除了旧 probe 的图/工具/业务逻辑。三处终态场景的 `cleanup_passed` 都是 false。

正常流式在 `handler.aclose()` 后另有一个 sse-starlette `_shutdown_watcher`，已在全部 pending task 枚举中保留。因此 `cleanup_passed` 的范围仅为 dispatcher 与记录到的 loop 错误，不代表当时整个事件循环零任务。各子进程 `asyncio.run` 返回后均只枚举到 MainThread；没有据此声称 OS 全系统线程/进程树已经验收。官方示例的 `running_tasks` set 也不是清理证明。

脚本保持 Python 自动 GC，故重复拒绝后的 dispatcher 数量不单调。正式 lifespan 关闭后另外执行一次明确标注的诊断 `gc.collect()`，保留 pending 销毁和 `ContextVar ... different Context` 告警，绝不以 GC 后数量归零当作正确关闭。未手动 cancel SDK 私有任务、关闭日志或吞异常。未测持续服务压力、崩溃恢复、不存在任务 start 失败、直接 Message/INPUT_REQUIRED、外部 worker 回收。

首次准备失败目录 [pna0yilq](a2a-official-minimal-20261005-pna0yilq/summary.json) 是源码快照多一个换行导致校验失败；第二次 [4lh3i44k](a2a-official-minimal-20261005-4lh3i44k/summary.json) 是我方 client 参数误用 Message 而非 SendMessageRequest。均在实际业务请求成功前失败，日志保留。修正后 [mplamgsj](a2a-official-minimal-20261005-mplamgsj/summary.json) 首次复现；最终 `_409m91j` 增加正常非流式对照和源码身份检查。没有用这些准备失败证明 SDK 缺陷。

## 原因及上游状态

安装包中 ActiveTask、registry、EventQueueSource、V2 handler 四文件的 LF 内容 Git blob 均与官方 v1.2.1 相同；[上游核对与 blob 记录](a2a-official-minimal-upstream-20261005.json)保留比对。根因与运行结果吻合：

1. [ActiveTask 构造](https://github.com/a2aproject/a2a-python/blob/v1.2.1/src/a2a/server/agent_execution/active_task.py#L436)创建两个 EventQueueSource；[队列构造](https://github.com/a2aproject/a2a-python/blob/v1.2.1/src/a2a/server/events/event_queue_v2.py#L57)立即启动 dispatcher。
2. [start 的终态异常路径](https://github.com/a2aproject/a2a-python/blob/v1.2.1/src/a2a/server/agent_execution/active_task.py#L529)在 producer/consumer 启动前失败，只设 finished 并安排 cleanup，没有关闭队列。
3. [registry._remove_task](https://github.com/a2aproject/a2a-python/blob/v1.2.1/src/a2a/server/agent_execution/active_task_registry.py#L118)只 pop；随后 `registry.aclose()` 的快照找不到被移出的对象。最终流式场景实测 registry=0、dispatcher=2。

截至核对时，[最新 release v1.2.1](https://github.com/a2aproject/a2a-python/releases/tag/v1.2.1) 为 2026-09-30，commit `041c17bbe8d5ced7a8f6c48761152ce01ffbfc14`。[main 固定 SHA e649325e](https://github.com/a2aproject/a2a-python/commit/e649325e041e44c0b0fe57e3eef0699cad164a1e) 为 10-03；[相对 release 的 13 个提交](https://github.com/a2aproject/a2a-python/compare/v1.2.1...e649325e041e44c0b0fe57e3eef0699cad164a1e)仅改变 ActiveTask 终态错误文案，registry/EventQueueSource 没变。**main 未安装或实跑；“未修复”是固定源码路径比对结论。**

| 上游条目 | 核对状态与关系 |
| --- | --- |
| [PR #1178](https://github.com/a2aproject/a2a-python/pull/1178) | Open，09-30 更新；在创建 ActiveTask 前拒绝终态，目的是避免提前写 push config，可避开本例，但未合并，不能当已发布修复。 |
| [PR #1179](https://github.com/a2aproject/a2a-python/pull/1179) | Open，09-11 更新；同一 start 失败路径，但 diff 只同步移除 registry，没有关闭队列，不解决这里的资源问题。 |
| [PR #1105](https://github.com/a2aproject/a2a-python/pull/1105) / [#1122](https://github.com/a2aproject/a2a-python/pull/1122) | 已合并、随 v1.1.2 发布；增加 aclose / 等待 producer，但本例失败早于 producer 创建，仍漏过关闭。 |
| [Issue #1296](https://github.com/a2aproject/a2a-python/issues/1296) | Open，10-02；direct Message / input-required 的 registry 与四后台任务留存，相关但与本例“registry已移除、两个dispatcher残留”不同。 |

查询覆盖 ActiveTask、EventQueueSource、terminal/start/aclose/dispatcher 相关 issue、PR、release 与源码差异；不是穷尽所有讨论，也未向上游发消息。

## 单机 V1 决策建议

**不阻塞当前受限本机短验证业务演示；仍阻塞“异常路径完整清理/生产生命周期合格”的声明。** V1 用 SDK 支持的完整输入→新 Task→COMPLETED 报告→GetTask 读回；candidate revision 的新验证显式创建新 Task，终态不追加输入。流式和非流式正常新任务两条路径在本最小对照均无 dispatcher 告警，简单同步 JSONRPC 足以先跑短验证。

客户端可基于已知终态禁止“继续此任务”操作并明确显示错误；不能偷偷把失败重发转换成新业务操作，也不能认为客户端检查保护了所有恶意请求/竞态。服务遇到此负例仍应暴露官方错误并保留清理失败。当前不补丁、不 fork、不改安装包，不让框架修复吞掉业务主线。若以后确需面向常驻/外部调用，可独立验证小型可替换边界修复或已发布上游修复，再重跑该 probe；本轮没有把任何候选修复当成已验证。
