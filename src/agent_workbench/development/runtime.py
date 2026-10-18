"""One native Runtime task; project-specific capabilities are host dynamic tools."""
import json
import os
from pathlib import Path
import subprocess
from ..coding.runtime_adapter import runtime_config, thread_params, safe_environment
from .tools import TOOL_SPECS

INSTRUCTIONS='''你是灰塔游戏研发助手。根据用户的新需求，调查隔离候选中的源码、配置与可信回归，自己决定调查和修订步骤。
先用project_status了解版本和范围，按需检索和读取；只能修改候选中的Python规则或v2配置，不能编辑可信测试、原项目、发布或访问网络。
write_file使用完整文件文本和最新SHA，必要时分段读完整文件后再修改。保持无关行为与现有接口兼容。
发现不明确或冲突需求时说明，不擅自扩展范围。可用start_diagnostic调查实际行为，但其结果只算观察。
选择适当start_check可信回归；立即获得的是作业号，不是通过。检查在后台进行，read_check返回真实结果；pending可继续调查，避免无意义轮询。
失败后阅读证据并修订，再检查。每次编辑都会使旧检查过时，只有与当前候选一致的可信结果才能支持通过。
结果未知不得当失败重跑。模型解释不能覆盖真实失败，也不能把探索诊断或范围校验当全部回归通过。
你是单Agent基线，不启动子Agent或Review。最终用中文说明改了什么、为什么、实际检查、未解决问题与限制；没有执行证据就明确说未验证。'''


def build_config(home,workspace,endpoint):
    return runtime_config(home,workspace,home/'unused',Path('unused'),endpoint,'single',include_legacy_mcp=False)


def parameters(workspace):
    return {**thread_params(workspace,'single'),'developerInstructions':INSTRUCTIONS,'dynamicTools':TOOL_SPECS}


def run_runtime(*,runtime_python,tools_python,workspace_control,control,endpoint,prompt,timeout_seconds=360):
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>8000:
        raise ValueError('require a bounded development request')
    if type(timeout_seconds) is not int or not 10<=timeout_seconds<=600:raise ValueError('invalid Runtime deadline')
    control=Path(control).resolve()
    workspace_control=Path(workspace_control).resolve()
    if control.is_relative_to(workspace_control/'workspace'):raise ValueError('Runtime control must be outside editable workspace')
    build_config(control,workspace_control/'workspace',endpoint)
    control.mkdir(parents=True,exist_ok=False)
    request={'workspace_control':str(workspace_control),'control':str(control),
             'tools_python':str(Path(tools_python).resolve()),'endpoint':endpoint,'prompt':prompt,'timeout_seconds':timeout_seconds}
    env=safe_environment(os.environ,Path(__file__).resolve().parents[2])
    try:
        result=subprocess.run([str(runtime_python),'-B','-m','agent_workbench.development.runtime_worker'],
            input=json.dumps(request,ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,
            cwd=control,env=env,timeout=timeout_seconds+20)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Runtime deadline reached; candidate and existing check receipts are retained') from None
    (control/'worker-stderr.txt').write_text(result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError('Runtime failed; see '+str(control/'result.json'))
    return json.loads(result.stdout)
