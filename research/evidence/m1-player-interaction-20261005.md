# M1 玩家操作、恢复读取与退出故障

> 后续更新：下文保留补丁前的现场记录。现6000.3.21f1已在同存档/UIA/Alt+F4场景正常退出，新营地与键盘演示见[演示结果](story-demo-20261005.json)。对应旧JSON仍是当时失败快照，不改写为成功。

2026-10-05，Asia/Shanghai。本轮没有模型调用或新战斗；继续用户已打开的同一局。它补充此前 M1 记录，不覆盖旧失败或引擎封存结果。

用户在 Unity 中选择破盾战技并执行。故障代理让 Host 正常结算后丢弃响应，用户再点击「重试同一行动」。截图显示首领生命 13816/14000、韧性 210/300、战技点 2、击破手能量 30，接下来轮到支援角色。Development Console 的 `Empty reply from server` 对应此次有意丢响应；它不代表重试又结算了一次。

## 真实行动和重试

- 会话 `play_7805592e7fc84f98bf055afc8a9bea7f`，命令 `cmd_a401a0232db546af94c2c276f23696a9`。
- 18:20:26 首次 POST 已成功但响应被丢；18:20:36 原请求重试。两次请求字节完全相同。Host 只有 1 条命令记录、revision 1、11 个事件，完整收据、权威快照、Unity 导出的 14 个全局字段及 4 个单位状态一致。
- 首版检查器误把响应的 JSON 对象键顺序也作为收据身份，产生失败。首次现场收据按组装顺序编码，重复请求从 SQLite 中读回规范编码；所有字段、类型、数组顺序相同。检查器现保留请求字节一致要求，响应比较完整 JSON 语义，并拒绝重复键；原始响应 hash 差异和第一份失败报告都保留。
- 新 `business-check-02.json` 通过，独立助手复核了 Unity 请求、代理原始请求/响应与唯一账本记录。父任务对检查器及启动器 37 项定向测试通过。测试证明检查逻辑，不替代此次真人操作。

原件：`D:/Desktop/graytower-game/local-data/unity-live-business-v1`。用户截图另存 `user-after-retry.png`，SHA256 `b6832e8faca8a3ec3acef4285a0e45cca748271d925c886c47bf5d70a6fbe8cf`。真人完成操作与截图只作为人工体验证据，不记为自动 OS 战斗输入通过。

## 重启与正式入口

独立 Player 重启和正式 `scripts/play_live.py --data ... --evidence` 都恢复了同一 revision、完整状态与合法行动；每次只有读取会话与事件的两个 GET，没有提交新行动。正式入口使用原存档的逐字节副本，原始证据保持不变。默认 D3D11 与已通过的图形验收一致；`--evidence` 是默认关闭的调试选项。

第一份恢复探针在读回成功后达到 90 秒时限并关闭自己的 Job，记录 `timed_out=true`；不能称为正常退出。正式入口恢复成功后，通过原生 Alt+F4 关闭窗口，Player 返回 `3221225477 / 0xC0000005`，启动器按失败报告并回收自己的 Host。Windows Application 1000/1001 同时确认 `UnityPlayer.dll + 0xc2ecc9` 访问冲突。进一步查到 18:24 的旧 Player 关闭也出现同一故障，故日志里的 `Shutdown` 或 `PlayerConnection::Cleanup` 不能当作成功退出的证明。

原件分别在 `local-data/unity-player-recovery-v1`、`local-data/launcher-restore-v1`；后者当次启动为 `20261005T103321Z-7280feae`。已确认态恢复与「未确认命令跨 Player 重启重试」是两个验收项，本轮只完成前者。

## 退出故障定位与处理选择

对两个现有 Windows dump 只读解析异常栈，并核对本机安装包的匹配 DLL/PDB 后，确认直接调用者是 `RuntimeStatic<PlatformAccessibilityManager,0>::StaticDestroy`，在清理时读取已经为空的 `GetScreenManager()` 的字段。故障地址恰好显示 GPU profiler 相关符号，但该名字不足以定责；直接调用栈和机器码把问题定位到 Windows 无障碍组件清理。

这与 Unity 官方 UUM-146676 高度吻合：[6000.3.21f1 修复说明](https://unity.com/releases/editor/whats-new/6000.3.21f1)记录了 UI Automation 访问后 Windows Player 关闭崩溃的修复。因此采用官方补丁版本并重新构建验收，保留 6000.3.19f1 与全部旧证据；不改引擎 DLL、不屏蔽失败退出码，也不通过关掉无障碍验收来宣称修复。

额外做了一次同包、同输入的对照，只省略显式 UIA 树查询，仍通过原生工具取得窗口并 Alt+F4；该次也崩溃。工具内部与其他进程的 UIA 交互未被隔离，因此它不能证明显式树查询是唯一触发源，亦不能反驳 dump 的直接证据。失败原件保存在 `local-data/launcher-uia-control-v1`。补丁尚需在同一场景重测，官方修复说明本身不是本项目已经修好的证明。

## 尚未通过的门槛

当前 M1/G0-U 不关闭：退出崩溃需要定位修复，自动截图工具的超时仍阻碍完整自动 OS 战斗输入；胜负完整玩家链、pending 命令跨重启、交付包与性能验收继续按既定路线完成。游戏可恢复读取和单次幂等成功不折算成这些项目通过。NPC 领域与框架实现可独立推进，完整中文使用手册仍随整套产品完成后交付。
