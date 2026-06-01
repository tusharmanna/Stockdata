@echo off
:: Weekly scanner — run once per week (e.g. Sunday evening).
:: Downloads latest prices then runs Momentum / StockbeeMomentum /
:: Double Trouble / TI65 / Parabolic scans.
:: Saves PDF chart and updates WeeklyWatchlist.txt.

cd /d "%~dp0"

set LOG_DIR=%~dp0logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set LOG_FILE=%LOG_DIR%\%dt:~0,4%-%dt:~4,2%-%dt:~6,2%_weekly.log

echo === Weekly scan started: %date% %time% === >> "%LOG_FILE%"
python "%~dp0main.py" 2>&1 | powershell -Command "$input | Tee-Object -FilePath '%LOG_FILE%' -Append"
python "%~dp0weekly_scanner.py" 2>&1 | powershell -Command "$input | Tee-Object -FilePath '%LOG_FILE%' -Append"
echo === Weekly scan finished: %date% %time% === >> "%LOG_FILE%"
pause
