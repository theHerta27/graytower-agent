# LangGraph离线探针运行说明

2026-10-04，研究脚本为 [langgraph_recovery_probe.py](../probes/langgraph_recovery_probe.py)。

1. 原旧项目Python环境没有LangGraph/LangChain。项目内创建独立`research/.venv-framework`；uv默认缓存被沙箱拒绝，获准后使用项目内cache；PyPI请求被沙箱拒绝，获准后安装依赖。没有修改旧产品环境。
2. 首次运行跨进程effect/interrupt部分完成，到`component_case → ToolNode.invoke`出现`ValueError: Missing required config key 'N/A' for 'tools'`。这是原始失败摘要，首次run未产生成功result.json；临时数据库保留，未以部分结果宣称完整通过。
3. 检查已安装`langgraph/_internal/_runnable.py`运行时注入与`langgraph/prebuilt/tool_node.py`的Runtime必填签名，定位为脱离编译图直接invoke缺上下文。将只读ToolNode放进MessagesState图，由图驱动注入Runtime；未改框架源码。
4. 重跑整个脚本，退出码0，[result.json](langgraph-20261004-mtqwchsr/result.json)为全部通过的证据；两个effect案例均真子进程退出73、三次新进程恢复及一次旧checkpoint回放。Provider仅MockTransport，游戏/世界动作均小型fixture。

复现（新运行生成新证据目录，不覆盖旧结果）：

```powershell
& 'D:\Desktop\mihoyo-agent-project\research\.venv-framework\Scripts\python.exe' `
  'D:\Desktop\mihoyo-agent-project\research\probes\langgraph_recovery_probe.py'
```

完整依赖版本见 [framework-requirements.lock.txt](../probes/framework-requirements.lock.txt)。当前研究环境Python3.11.9；包版本精确锁定但此freeze文件不是带wheel hash的生产供应链锁，正式实施仍须生成可追溯安装锁并验证Python3.12。
