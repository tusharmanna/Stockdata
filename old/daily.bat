@echo off
cd /d "%~dp0"
python main.py && python scanner.py
pause
