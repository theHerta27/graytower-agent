@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo 灰塔 AI 研发任务中心
echo 正在检查本地环境，请稍候……
echo 页面地址：http://127.0.0.1:18784/tasks
if not exist ".venv\Scripts\python.exe" (
  echo 缺少 Python 环境，请按 GitHub使用手册.md 安装。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -B -c "import json,urllib.request; s=json.load(urllib.request.urlopen('http://127.0.0.1:18784/api/tasks',timeout=3)); raise SystemExit(0 if isinstance(s.get('tasks'),list) else 1)" >nul 2>nul
if not errorlevel 1 (
  echo 任务中心已在运行，正在打开浏览器。
  start "" "http://127.0.0.1:18784/tasks"
  exit /b 0
)
if not exist "frontend\dist\index.html" (
  echo 前端尚未构建，请在 frontend 目录执行 npm ci 和 npm run build。
  pause
  exit /b 1
)
echo 查看旧报告、规则试玩不调用模型；代码检查需要 Docker Desktop 正常运行。
echo 请保持此窗口打开；结束服务按 Ctrl+C。
start "" "http://127.0.0.1:18784/tasks"
".venv\Scripts\python.exe" -u -X utf8 -B scripts\serve_v1_product.py
echo 服务已结束；出现错误时请保留上方信息。
pause
