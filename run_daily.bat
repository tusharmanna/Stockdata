@echo off
cd /d E:\work\Stockdata

set LOG_DIR=E:\work\Stockdata\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set LOG_FILE=%LOG_DIR%\%dt:~0,4%-%dt:~4,2%-%dt:~6,2%.log

echo. >> "%LOG_FILE%"
echo === Run started: %date% %time% === >> "%LOG_FILE%"
python main.py >> "%LOG_FILE%" 2>&1
python scanner.py --no-display >> "%LOG_FILE%" 2>&1
python qqq_signal.py >> "%LOG_FILE%" 2>&1
echo === Run finished: %date% %time% === >> "%LOG_FILE%"
