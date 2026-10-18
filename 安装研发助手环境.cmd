@echo off
chcp 65001 >nul
echo 安装本机依赖，不会调用模型。请先启动Docker Desktop。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_development_environment.ps1"
pause
