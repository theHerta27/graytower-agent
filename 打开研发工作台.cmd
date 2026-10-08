@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
echo 灰塔前哨研发工作台
echo 页面地址：http://127.0.0.1:8767/
echo 默认关闭新模型调用，可查看已有候选和运行记录。
echo.
if not exist ".venv\Scripts\python.exe" (
  echo 找不到项目 Python 环境，请按 GitHub使用手册.md 安装依赖。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -B -c "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8767/api/status',timeout=2); s=json.load(r); raise SystemExit(0 if s.get('profile')=='trusted-combat-numeric-v1' and 'coding' in s and 'model' in s else 1)" >nul 2>nul
if not errorlevel 1 (
  echo 工作台已在运行，正在打开浏览器。
  start "" "http://127.0.0.1:8767/"
  exit /b 0
)
if not exist "frontend\dist\index.html" (
  echo 前端尚未构建，请在 frontend 目录执行 npm ci 和 npm run build。
  pause
  exit /b 1
)
echo 正在启动服务，并打开浏览器；首次加载若尚未连接，请稍后刷新。
echo 请保持此窗口打开。关闭服务可按 Ctrl+C。
start "" "http://127.0.0.1:8767/"
".venv\Scripts\python.exe" -u -X utf8 -B -m agent_workbench.cli --data local-data/coding-workbench-v1 web --port 8767
echo.
echo 工作台服务已结束；若上方出现错误，请保留错误信息。
pause
