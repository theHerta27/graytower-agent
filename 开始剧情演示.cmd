@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -X utf8 -B scripts\play_story.py
pause
