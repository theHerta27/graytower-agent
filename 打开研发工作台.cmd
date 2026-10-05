@echo off
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
".venv\Scripts\python.exe" -X utf8 -B -m agent_workbench.cli --data local-data/coding-workbench-v1 web --port 8767
pause
