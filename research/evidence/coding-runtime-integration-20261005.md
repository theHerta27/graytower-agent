# Coding 正式 Runtime 接入：离线实现与真实验收准备

日期：2026-10-05。状态：实现与离线集成通过，新的 DeepSeek 业务验收待用户授权。G0-C/M2 未据此关闭。

## 用户会怎样使用

研发人员希望“把击破手战技倍率从 1.4 调到 1.58，保留战技点消耗、削韧及其他配置”。Coding 在独立工作区阅读真实配置文件、修改文本、调用程序检查完整差异、运行原生 Review，再冻结带来源的候选。确认后，候选走现有 A2A 交给独立 QA；QA 决定如何查证并返回证据报告。候选不会自动写回游戏或发布。

当前只支持真实配置文件编辑。它与 Config 的区别是 Runtime 自主使用文件工具完成读、改、查及 Review，而非 Config 图生成结构化编辑提议。它尚不是任意代码编写、运行 shell、代码构建或 Unity 测试能力。

## 已落实的技术取舍

| 层 | 本轮实现与边界 |
| --- | --- |
| 官方 Runtime | 发布版 `openai-codex==0.160.0`，使用包默认精确依赖的 `openai-codex-cli-bin==0.160.0`。拥有主循环、原生 spawn/wait/close、上下文和 Review；不改 SDK、不实现 Python 子调度器。 |
| Python 业务适配 | 无凭据的独立 SDK 进程、任务开始时 `single`/`auto`、事件和回执、原生 Review 的持久结果查询、候选来源绑定。不是新一层模型循环。 |
| 工具权限 | 关闭 shell、apply_patch、view_image；原生 MCP 仅 list/read/check。只有主线程持有 SDK 动态 `edit_text` 写能力，按真实 threadId 校验。fresh child 无该工具，fork child 即使继承声明也会被宿主拒绝。 |
| DeepSeek 兼容 | 原生 Runtime 实际发送 `multi_agent_v1`/`mcp__coding_readonly` namespace；仅在 Responses 边界无损转换函数名，保留参数、call ID、事件和 usage。未知 namespace、碰撞和未广告工具拒绝，不改分工消息或强制角色人数。 |
| 费用边界 | 父、子、Review 共用一个 SQLite 请求账本，外发前预留，失败/未知占额，重开不重置。凭据仅在官方 DeepSeek sender 中；不传给 Runtime/MCP。HTTP 不自动重试、不跟随重定向、无其他模型服务回退。 |
| 候选与独立 QA | 完整工作区只允许一个配置文件和其目录；额外文件、其他 JSON 改动、重复 key、链接及并发变动拒绝。冻结原始字节/全树/hash/diff，`author=coding`、`kind=numeric_config`，复用现有 Card/client/QA。`code/build` 继续拒绝。 |

`auto` 允许主 Agent 按任务使用 0..N 原生子 Agent，不预设固定分工。当前本机资源配置最多四个并发子线程、两层深度，费用总额另有硬限；这是资源上限，不是必须创建的 Agent 数。实际 spawn 事件和允许模式分别记入回执。

Review 只是一份绑定文件与完整树的原生模型意见，不等于独立 QA 通过；来源声明保持 `declared_unverified`，领域层不会把调用者提供的字符串当作通过证明。正式 runner 将完整 Runtime 回执存为不可变 artifact，并在导入前后核对候选树与 Review 树一致。

## 实测结果

- 官方版本 probe：`single/auto/review` 三项通过，最终 19 次本地脚本化 Responses。实际检查 native fresh/fork 子线程、MCP 进程、主线程 ID、越权写拒绝和 DeepSeek 路由。440 份协议 schema、二进制/SDK 身份及原始事件已保存。
- 产品最终切片：`slice-final-single` 5 次、`slice-final-auto` 10 次本地脚本化 Responses，均经过正式 namespace/预算传输层、官方 Runtime、官方 MCP 2.3、文件修改、完整检查及原生 Review，形成冻结 Coding 候选。协作切片实际创建 1 个原生子线程；并非用开发助手代替产品 Agent。
- A2A 准入测试实际启动本机服务并使用相同协议：Coding 确认候选可接收、重复业务 ID 复用结果，未确认、缺来源和不支持类型拒绝。QA 回调为零战斗测试实现，不能计作真实 QA 模型验收。
- 文件收据测试包含真实子进程 `os._exit(73)`：已准备未替换、已写未完成收据和重复调用均可核对；临时文件留在同卷控制目录，不污染候选树。未知/被其他修改覆盖的状态拒绝继续写。
- 最终全套 `189 tests`，187 通过、2 个既有 opt-in 战斗测试跳过；独立 Coding 环境 `pip check` 通过。前端未修改，不重复计算历史前端测试为本轮结果。
- 本轮 0 外部模型调用、0 新战斗、0 新模型费用。脚本化输出不证明 DeepSeek 兼容性、真实任务质量或多 Agent 相对收益。

Windows 发布 Runtime SHA256：`fdda5fa3cf3fb3d000b876720742857676293e4315e4b045fae6f8bd7e866d1d`。SDK wheel SHA256：`61d2d855ca2ebedfd51280fbeb60ff31fc47ccbd55ebce186505e3f3da096921`。依赖见 [Coding 锁文件](../../requirements-coding.lock.txt)。

## 保留的失败与修正

早期 probe 的通知消费、空线程 Review 持久化及枚举序列化失败均保留在 `offline-r1..r7`。正式 SDK 通用 `review/start` 不预注册 turn 通知，快速完成可能错过订阅；当前在完成普通任务后，通过公开 `thread/read` 查询持久 Review，无私有 router 补丁。

产品 `slice-r1/r2` 首个模型请求尚无 MCP 工具，记录未覆盖。当前在 turn 前用指定 thread/server 的 `mcpServerStatus/list` 预热并核对完整只读工具清单。独立审查还复现了临时文件污染候选树、Review 与导入树脱绑定及授权前游戏环境漂移；修复、负例和原始失败均保留。

修改领域适配代码会改变冻结的 worker 环境身份。旧 manifest 不重封、也不忽略漂移；旧报告/收据可读。需要在新环境重验时创建新的候选，不能把旧实验重新解释成新实现成绩。

## 下一批真实验收（尚未运行）

范围：`local-data/coding-runtime-demo-v1/outbound-scope.json`，SHA256 `bd9ff50285c0757d777932617f3e1ce9d01648e1d90b08d82fcac598d70e1c48`。已提出用户授权请求，未读凭据、未建立执行标记。

固定顺序 single→auto，两次相同配置需求用于功能验收；固定选 auto 候选经演示操作者按 manifest 确认后交同一 QA。仅 `deepseek-flash`，官方 Responses 最多 24 次＋Chat 最多 4 次；最多 4 场新战斗，不采纳、不发布。Coding USD0.65、QA USD0.20，总上限 USD0.85；按峰价/不使用缓存优惠保守上界 USD0.743616。具体数据、预览、源码/SDK/领域冻结身份均在 scope 中。

这不是公平效果实验，不比较两次结果就宣称协作更优。真实 DeepSeek 工具/Review/QA 成功后，再以需要独立调查的业务任务比较 single、资源增强 single 与协作，按原路线确认质量收益和代价。

最终退出仍要求真实业务示范。尚未交付：Coding 工作台页面、任意代码/构建受限 worker、完整任务取消/跨进程 SDK 恢复、Unity 可玩与自动测试、NPC。已落实的文件级恢复不外推到这些能力。

## 入口与证据

```powershell
$env:PYTHONPATH = 'src;tests;scripts'
$env:PYTHONUTF8 = '1'
# 本地脚本化模型，目录必须是新的；0 外发、0 战斗。
.venv/Scripts/python.exe scripts/check_coding_slice.py --out local-data/my-coding-check --mode auto --relay
# 准备新范围（不调用模型）；mode 可 single / auto / both。
.venv/Scripts/python.exe scripts/run_coding_demo.py --data local-data/my-coding-batch --mode both
```

真实运行需已授权的精确 `--authorization-sha256`；脚本验证预览、源码、SDK/CLI 和冻结领域候选后才读取凭据，并用独占执行标记防止误重跑。不能复制目录复用旧授权。

证据目录：`local-data/coding-runtime-v1/offline-r8`、`slice-final-single`、`slice-final-auto`、`full-tests-final.log`；[封存索引](coding-runtime-integration-20261005.json)。实现入口：[Runtime](../../src/agent_workbench/coding/runtime_adapter.py)、[文件能力](../../src/agent_workbench/coding/file_tools.py)、[候选导入](../../src/agent_workbench/coding/candidates.py)、[授权批次](../../scripts/run_coding_demo.py)。

官方依据：[Codex Python SDK](https://learn.chatgpt.com/docs/codex-sdk)、[原生子 Agent](https://learn.chatgpt.com/docs/agent-configuration/subagents)、[DeepSeek Responses 兼容说明](https://api-docs.deepseek.com/guides/responses_api/)、[函数 Schema](https://api-docs.deepseek.com/api/create-response/)、[计价](https://api-docs.deepseek.com/quick_start/pricing/)。引用日期 2026-10-05；实际兼容能力以版本化运行证据为准。
