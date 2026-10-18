param([int]$Port=18790,[switch]$NoBrowser,[switch]$NoModel)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$taskRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
Write-Host '[1/4] 正在准备灰塔研发助手……'
$taskPythonCandidates=@((Join-Path $taskRoot '.venv/Scripts/python.exe'),(Join-Path (Split-Path -Parent $taskRoot) 'mihoyo-agent-project/.venv/Scripts/python.exe'))
$taskPython=$taskPythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$taskSdkCandidates=@((Join-Path $taskRoot '.venv-coding/Scripts/python.exe'),(Join-Path $taskRoot 'research/.venv-coding/Scripts/python.exe'),(Join-Path (Split-Path -Parent $taskRoot) 'mihoyo-agent-project/research/.venv-coding/Scripts/python.exe'))
$taskSdk=$taskSdkCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (!$taskPython -or !$taskSdk) { throw '没有找到Python/官方SDK环境。请先双击“安装研发助手环境.cmd”。' }
if (!(Test-Path -LiteralPath (Join-Path $taskRoot 'frontend/dist/index.html'))) { throw '页面尚未构建。请先双击“安装研发助手环境.cmd”。' }
$env:PYTHONPATH=Join-Path $taskRoot 'src'
$env:PYTHONUTF8='1'
if (!$NoModel -and !$env:DEEPSEEK_API_KEY) { $env:DEEPSEEK_API_KEY=[Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User') }
Write-Host '[2/4] 页面和运行环境已找到。密钥不会显示在窗口中。'
$taskUrl="http://127.0.0.1:$Port"
try { $taskExisting=Invoke-RestMethod -Uri "$taskUrl/api/development/status" -TimeoutSec 2 } catch { $taskExisting=$null }
if ($taskExisting) {
    if ($taskExisting.application -ne 'graytower-development-workbench' -or $taskExisting.workbench_root -ne $taskRoot) { throw "端口 $Port 已由其他工作台占用，请关闭它或使用 -Port 指定新端口。" }
    Write-Host "[4/4] 工作台已经运行：$taskUrl/development"
    if (!$NoBrowser) { Start-Process "$taskUrl/development" }
    exit 0
}
Write-Host '[3/4] 正在启动本地服务。浏览器会在就绪后打开。'
Write-Host '浏览、创建候选和本地检查不调用模型。只有在页面确认材料和费用后才开始收费任务。'
Write-Host '请保留此窗口；按 Ctrl+C 停止服务。'
$taskArgs=@('-u','-B','-m','agent_workbench.development','serve','--data',(Join-Path $taskRoot 'local-data/development-workbench'),'--port',"$Port",'--runtime-python',$taskSdk)
if (!$NoBrowser) { $taskArgs+='--open-browser' }
if ($NoModel) { $taskArgs+='--no-model' }
& $taskPython @taskArgs
if ($LASTEXITCODE -ne 0) { throw '工作台未正常启动，请查看上方具体错误。' }
