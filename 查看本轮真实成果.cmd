@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PYTHONUTF8=1"
set "GT_RESULT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%GT_RESULT_PYTHON%" set "GT_RESULT_PYTHON=%~dp0..\mihoyo-agent-project\.venv\Scripts\python.exe"
if not exist "%GT_RESULT_PYTHON%" (
  echo 没有找到运行环境，请先运行“安装研发助手环境.cmd”。
  pause
  exit /b 1
)
if not exist "%~dp0local-data\completion-20261027\campaign-v1\campaign-close.json" (
  echo 本机没有本轮原始结果，请阅读 research\evidence\completion-20261027.md。
  pause
  exit /b 1
)
set "GT_RESULT_BROWSER=--open-browser"
if /I "%~1"=="--no-browser" set "GT_RESULT_BROWSER="
echo 正在打开本轮真实任务、候选修改和检查结果。
echo 此入口关闭模型，不产生新模型费用。采用按钮仍需你明确确认，请先审阅差异。
echo 地址：http://127.0.0.1:18797/development
echo 请保留这个窗口；按 Ctrl+C 停止服务。
"%GT_RESULT_PYTHON%" -m agent_workbench.development serve --data "%~dp0local-data\completion-20261027\campaign-v1" --port 18797 --no-model %GT_RESULT_BROWSER%
if errorlevel 1 pause
