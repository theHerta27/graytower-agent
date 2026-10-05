# M1 游戏会话与 Unity 实施记录

日期：2026-10-05。新游戏仓库为 `D:/Desktop/graytower-game`，旧 `combat-foundation` 保持只读。本记录是阶段进展，不是 M1、G0-U 或全产品完成声明。此轮不调用大模型。

代码已提交至游戏分支 `m1-playable-session`：核心 `ddd81a3`，实时客户端与执行器 `18b2d00`。结构化来源与阶段状态见[证据索引](m1-game-unity-20261005.json)。

玩家需要亲手选择技能与目标，断线后能继续同一场战斗，不能因为重试再扣一次战技点。当前实现让真人输入和 Bot 都驱动同一个 Python `BattleSession`：规则、随机数、行动阶段和事件在这里结算；本机 Host 将状态和命令收据一起写入 SQLite；Unity 只提供合法选项、提交命令和显示权威状态。

一次行动提交前，Unity 已把完整命令和固定 ID 写入本地存档。若服务端已经执行但成功响应丢失，客户端保留原命令，重试时读取同一份收据；随后获取最新状态，避免将旧收据误当成当前画面。这个设计已有领域/客户端工程测试，真实 Player 故障现场仍待补证。

## 实际证据

- 游戏核心已提交为 `ddd81a3`：迁移前 6 份完整黄金 Trace 一致，真实 HTTP 脚本完成一局 85 条命令并获胜，第 5 条命令后重启 Host、同 ID 重试收据一致。完整重放从冻结初始输入重新计算，核对全量状态，原数据库哈希不变。见 [核心证据](../../../graytower-game/docs/evidence/m1-session-host-20261005.json)。该脚本不是玩家 OS 输入。
- Unity 6000.3.19f1 的产品 EditMode 2/2、PlayMode 1/1、UTF Player 1/1 通过，Windows Mono 产品构建成功。首轮编译命名空间错误和 UTF Player Null 图形设备失败保留；后者改用 D3D11 运行，没有放宽 Shader 检查。结果目录为 `graytower-game/local-data/unity-live-v1`。
- 固定引擎记录见 [6 次尝试与源码封存](../../../graytower-game/docs/evidence/m1-unity-engine-20261005.json)。父任务独立核对了 93 项引用、完整产品目录 236 文件，以及基础设施探针 184 项产物和 6 份源码。历史 runner 随后增加自动封存功能，旧引用通过修改前的精确字节归档核验，未重写原报告。
- UTF 的 UI 测试创建实际 uGUI Button/EventSystem 并触发组件回调；这是引擎测试，不是操作系统鼠标点击。完整组件读回导出包含全局状态和各单位属性，不只导出服务端 JSON 的副本。
- 独立 Unity 基础设施探针在宿主身份通过 EditMode、PlayMode、构建及非 UTF Player smoke；受限身份因无许可证退出 198。宿主成功不能代替受限代码 Worker 的 G0-U 门槛，原探针结果保存在 `local-data/unity-editor-smoke-v1/evidence-index.json`。

## 尚未完成的现场环节

当前本机故障代理只丢弃下一次已经由 Host 成功完成的命令响应，保存原始请求、原始收据和哈希。17:47 独立只读检查时数据库尚无会话；17:56 真实 Unity 已创建 `play_7805592e7fc84f98bf055afc8a9bea7f` 并读回 revision 0，初始组件状态已导出，但行动与丢响应重试尚未发生。窗口采集在恢复、重选目标和更换 D3D11 后仍超时；没有凭推测坐标点击，也没有将 HTTP 流量写成 OS 操作证据。

已请用户协助完成“新战斗→选择技能与目标→执行→重试同一行动”。收到现场结果后，需要同时核对 Unity 请求/收据、代理原始记录、SQLite 唯一命令和组件状态。若用户执行，这一步记录为真人操作，自动 OS 门槛仍保留。

Player 跨进程恢复还需单独留下重启前待确认命令、旧进程退出、新进程启动及重启后的相同请求链；只读验收脚本的 `passed` 不能单独证明这一点。独立复核见 [现场证据边界](../../../graytower-game/docs/evidence/m1-live-business-review-20261005.json)。

18:02 对实际初始组件做了独立只读核对：同一会话 revision 0 的 14 个全局字段、全部 4 个单位逐字段一致，journal、视图和数据库哈希在读取前后不变。记录为 `graytower-game/local-data/unity-live-business-v1/initial-component-check-01.json`。这是实际组件读回证据，仍不是行动、故障重试或 OS 自动输入通过。

收尾检查还用隔离 Python 子进程复现了旧执行 helper 的竞态：进程启动后才加入 Job，已经提前创建的子进程可能漏出回收范围。现在先挂起创建、加入 Job，再恢复线程，失败路径按专属句柄终止；真实 Python base/venv 子进程和异常清理测试已通过。旧引擎记录只能证明其已记录的根进程回收和 Job 关闭，不能被新修复倒算成完整子进程清理证明。原 helper、复现及改后验证保存在 `graytower-game/local-data/job-ownership-race-v1`。

修复后补跑一次真实 Unity EditMode（attempt03）：2/2 通过，耗时 9.297 秒，源码未改变；14 个记录中的所属进程在 Job 关闭后全部不存在。这个新增结果独立保存，不覆盖前述 6 次尝试的历史 seal，也不代表新的 UTF Player/OS 验收。

父任务完整辅助 suite 的 v2 为 62 项通过；v1 因父进程按 GBK 解码子进程的 UTF-8 输出失败，未能取得完整结果，明确保留为不可判定，不计通过。第二轮保留原始字节和结构化记录，见 `graytower-game/local-data/m1-final-helper-validation-v2`。它们属于工程检查，不是游戏体验或模型质量评分。

随后定向确认了测试自身的 marker 半写观察窗口，将测试握手改成原子发布，单文件 6/6 通过；产品源码没有再变，不能据此断言首轮采集失败的原因。修复、真实引擎补验、初始组件读回及修改前源码统一收录在 [后续证据](../../../graytower-game/docs/evidence/m1-runtime-followup-20261005.json)。

## 启动与后续

游戏仓库已提供中文 `开始试玩.cmd`、PowerShell 和 Python 入口，当前使用说明在 [游戏 README](../../../graytower-game/README.md)。它们面向可信的单机试玩，不是运行未知候选代码的安全沙箱。启动器真实开关、恢复和进程回收仍需现场验收；完整分发包和全新机器安装尚未交付。

下一步先完成上述现场链路，再接 NPC 世界支援和后续代码/build 验证、桌面集成与四能力联合演示。最终使用手册用中文，按实际入口讲清安装、配置、任务、确认、验证、试玩、恢复和证据阅读，不把未完成能力写成可用功能。
