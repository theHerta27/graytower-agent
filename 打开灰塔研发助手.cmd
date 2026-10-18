@echo off
chcp 65001 >nul
echo 正在打开灰塔研发助手，请稍候……
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_development_workbench.ps1"
if errorlevel 1 pause
