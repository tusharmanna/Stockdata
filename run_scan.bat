@echo off
set LOG_DIR=%~dp0logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set LOG_FILE=%LOG_DIR%\%dt:~0,4%-%dt:~4,2%-%dt:~6,2%.log

echo === Run started: %date% %time% === >> "%LOG_FILE%"
python "%~dp0run_scan.py" 2>&1 | powershell -Command "$input | Tee-Object -FilePath '%LOG_FILE%' -Append"
echo === Run finished: %date% %time% === >> "%LOG_FILE%"
pause
