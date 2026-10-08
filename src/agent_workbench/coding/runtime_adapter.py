"""Business adapter around the pinned official SDK, without an Agent loop.

The SDK runs in a dedicated process with no provider credential. A separately
owned loopback Responses endpoint controls outbound authorization and budget.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

from .file_tools import EDIT_TOOL

MODEL = 'deepseek-flash'
VERSION = '0.160.0'
INSTRUCTIONS = '''你是游戏研发 Coding Agent。阅读当前隔离工作区，理解需求后修改文件并检查。
当前 V1 只支持击破手战技倍率配置文件编辑；保持其他内容不变。工具执行与校验结果才是事实。
可按任务价值使用原生子 Agent 调查、检查，但不要为简单修改强行分工；说明实际分工。
子 Agent 只有工作区只读工具，主线程独占 edit_text。不能通过提示词要求其他工具写入。
不要确认、应用或发布候选，不要声称总体统计收益。最终说明改动、已做检查与仍待 QA 的部分。'''

PYTHON_INSTRUCTIONS = '''你是游戏 Python 逻辑修复 Coding Agent。阅读工作区源码和业务需求，定位护盾与生命扣减故障。
这是自有游戏的受控故障案例。只能通过 edit_text 修改 game-core/combat_core/v2/effects.py；其余源码只读。
不能调用 shell、执行候选代码、访问外部网络、修改评测规则或读取工作区外文件。
check_workspace 只核对编辑范围和文件身份，不是运行测试。实际隔离测试由独立 Verification 负责。
可以按价值使用原生子 Agent 只读调查；主线程独占编辑，禁止通过其他工具写入。
保持无关机制不变。修复后提交清楚的修改说明和仍待 QA 的部分；不能自称已通过测试。'''


def instructions(profile=None):
    if profile is None or profile == 'trusted-combat-numeric-v1':
        return INSTRUCTIONS
    if profile == 'shield-damage-python-v1':
        return PYTHON_INSTRUCTIONS
    raise ValueError('unsupported Runtime business profile')


def safe_environment(source, source_root: Path):
    env = {key: value for key, value in source.items() if key.upper() in {
        'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'TEMP', 'TMP',
        'USERPROFILE', 'COMSPEC', 'PROCESSOR_ARCHITECTURE'}}
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(source_root),
               NO_PROXY='127.0.0.1,localhost', LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false')
    return env


def _mode(mode):
    if mode not in ('single', 'auto'):
        raise ValueError('mode must be single or auto')


def runtime_config(home: Path, workspace: Path, data: Path, tools_python: Path, endpoint: str, mode: str,
                   preparation: dict | None = None):
    _mode(mode)
    parsed = urlsplit(endpoint)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('Runtime requires the separately authorized local Responses endpoint')
    quote = lambda value: json.dumps(str(value), ensure_ascii=False)
    enabled = 'true' if mode == 'auto' else 'false'
    return '\n'.join([
        f'model = "{MODEL}"', f'review_model = "{MODEL}"', 'model_provider = "deepseek_local"',
        'approval_policy = "never"', 'approvals_reviewer = "user"', 'sandbox_mode = "read-only"',
        'web_search = "disabled"', 'model_reasoning_effort = "low"', 'model_reasoning_summary = "none"',
        'experimental_request_user_input_enabled = false',
        'project_doc_max_bytes = 0', 'model_catalog_json = ' + quote(home / 'models.json'),
        '[analytics]', 'enabled = false', '[features]', 'shell_tool = false', 'apps = false',
        'plugins = false', 'memories = false', 'code_mode = false', 'view_image = false', 'goals = false',
        'multi_agent_v2 = false',
        '[agents]', 'enabled = ' + enabled, 'max_concurrent_threads_per_session = 4', 'max_depth = 2',
        f'default_subagent_model = "{MODEL}"',
        '[model_providers.deepseek_local]', 'name = "DeepSeek authorized local endpoint"',
        'base_url = ' + quote(endpoint), 'wire_api = "responses"', 'requires_openai_auth = false',
        'supports_websockets = false', 'request_max_retries = 0', 'stream_max_retries = 0',
        '[mcp_servers.coding_readonly]', 'command = ' + quote(tools_python),
        'args = ' + json.dumps(['-B', '-m', 'agent_workbench.coding.readonly_mcp',
                               '--workspace', str(workspace), '--data', str(data),
                               '--preparation', json.dumps(preparation)], ensure_ascii=False),
        'startup_timeout_sec = 30', 'tool_timeout_sec = 30',
        '[mcp_servers.coding_readonly.env]',
        'PYTHONPATH = ' + quote(Path(__file__).resolve().parents[2]), 'PYTHONUTF8 = "1"',
        'PYTHONDONTWRITEBYTECODE = "1"', 'LANGSMITH_TRACING = "false"', 'LANGCHAIN_TRACING_V2 = "false"',
    ]) + '\n'


def model_catalog(*, profile=None):
    return {'models': [{
        'slug': MODEL, 'display_name': 'DeepSeek Flash', 'description': 'Bounded Coding V1',
        'default_reasoning_level': 'low', 'supported_reasoning_levels': [{'effort': 'low', 'description': 'low'}],
        'shell_type': 'shell_command', 'visibility': 'list', 'supported_in_api': True,
        'priority': 1, 'availability_nux': None, 'upgrade': None, 'support_verbosity': False,
        'default_verbosity': None, 'apply_patch_tool_type': None, 'web_search_tool_type': 'text',
        'truncation_policy': {'mode': 'tokens', 'limit': 10000}, 'context_window': 1048576,
        'experimental_supported_tools': [], 'input_modalities': ['text'], 'tool_mode': 'direct',
        'multi_agent_version': 'v1', 'auto_review_model_override': MODEL,
        'model_messages': {'instructions_template': instructions(profile)},
        'supports_reasoning_summary_parameter': False,
    }]}


def thread_params(workspace: Path, mode: str, *, profile=None):
    _mode(mode)
    return {'cwd': str(workspace), 'model': MODEL, 'modelProvider': 'deepseek_local',
            'allowProviderModelFallback': False, 'approvalPolicy': 'never', 'approvalsReviewer': 'user',
            'sandbox': 'read-only', 'developerInstructions': instructions(profile),
            'dynamicTools': [EDIT_TOOL], 'ephemeral': False}


def validate_runtime_receipt(receipt: dict, inspection: dict):
    """A completed native Review is an opinion bound to these exact file bytes."""
    if receipt.get('status') != 'completed' or receipt.get('review_turn', {}).get('status') != 'completed':
        raise ValueError('Runtime task and native Review must both complete')
    for left, middle, right in (('review_tree_hash', 'after_tree_hash', 'after_tree_hash'),
                                ('review_file_sha256', 'after_sha256', 'after_hash')):
        value = receipt.get(left)
        if (not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value)
                or value != receipt.get(middle) or value != inspection.get(right)):
            raise ValueError('Review receipt no longer matches the current workspace')


def run_runtime(*, runtime_python: Path, tools_python: Path, workspace: Path, data: Path,
                control: Path, preparation: dict, endpoint: str, mode: str, prompt: str, timeout_seconds=180):
    """Run one native task plus native review. No direct external model access."""
    _mode(mode)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        raise ValueError('require a bounded Coding request')
    if not 10 <= timeout_seconds <= 600:
        raise ValueError('invalid Runtime deadline')
    control = Path(control).resolve()
    control.mkdir(parents=True, exist_ok=False)
    request = {'workspace': str(Path(workspace).resolve()), 'data': str(Path(data).resolve()),
               'control': str(control), 'tools_python': str(Path(tools_python).resolve()),
               'preparation': preparation, 'endpoint': endpoint, 'mode': mode, 'prompt': prompt, 'timeout_seconds': timeout_seconds}
    source_root = Path(__file__).resolve().parents[2]
    result = subprocess.run([str(runtime_python), '-B', '-m', 'agent_workbench.coding.runtime_worker'],
                            input=json.dumps(request, ensure_ascii=False), text=True, encoding='utf-8',
                            capture_output=True, cwd=control, env=safe_environment(os.environ, source_root),
                            timeout=timeout_seconds + 20)
    (control / 'worker-stderr.txt').write_text(result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Coding Runtime failed; inspect the local control receipt')
    return json.loads(result.stdout)
