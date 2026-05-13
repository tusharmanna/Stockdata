@echo off
:: Run intraday breakout scanner and log output.
:: Called by Task Scheduler hourly 10:15 AM - 2:15 PM ET on weekdays.

set LOG_DIR=%~dp0logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set LOG_FILE=%LOG_DIR%\%dt:~0,4%-%dt:~4,2%-%dt:~6,2%.log

echo === BuyNow scan started: %date% %time% === >> "%LOG_FILE%"
python "%~dp0intraday_scanner.py" 2>&1 | powershell -Command "$input | Tee-Object -FilePath '%LOG_FILE%' -Append"
echo === BuyNow scan finished: %date% %time% === >> "%LOG_FILE%"
