@echo off
cd /d "%~dp0"

:: ── Log setup ─────────────────────────────────────────────────────────────────
set LOG_DIR=%~dp0logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set LOG_FILE=%LOG_DIR%\whitelight_%dt:~0,4%-%dt:~4,2%-%dt:~6,2%.log

echo === Whitelight run started: %date% %time% === >> "%LOG_FILE%"

:: ── Step 1: Download today's QQQ / TQQQ / SQQQ and recompute indicators ───────
python "%~dp0refresh_whitelight_data.py" 2>&1 | powershell -Command "$input | Tee-Object -FilePath '%LOG_FILE%' -Append"

:: ── Step 2: Compute signal and write whitelight_signal.txt ────────────────────
python "%~dp0whitelight_strategy.py" 2>&1 | powershell -Command "$input | Tee-Object -FilePath '%LOG_FILE%' -Append"

echo === Run finished: %date% %time% === >> "%LOG_FILE%"

:: ── Step 3: Parse whitelight_signal.txt ───────────────────────────────────────
set SIGNAL=UNKNOWN
set ACTION=HOLD
set INSTRUMENT=NONE
set HOLD_DAYS=0
set CONFIDENCE=LOW
set FILTERED=False

for /f "usebackq tokens=1,2 delims==" %%a in ("%~dp0whitelight_signal.txt") do (
    if "%%a"=="signal"             set SIGNAL=%%b
    if "%%a"=="action"             set ACTION=%%b
    if "%%a"=="instrument"         set INSTRUMENT=%%b
    if "%%a"=="hold_days_current"  set HOLD_DAYS=%%b
    if "%%a"=="confidence"         set CONFIDENCE=%%b
    if "%%a"=="whipsaw_filtered"   set FILTERED=%%b
)

:: ── Step 4: Windows toast notification ───────────────────────────────────────
set NOTIFY_TITLE=Whitelight: %ACTION% %INSTRUMENT%
set NOTIFY_BODY=Signal: %SIGNAL%  |  Hold: %HOLD_DAYS% day(s)  |  Confidence: %CONFIDENCE%
if "%FILTERED%"=="True" set NOTIFY_BODY=%NOTIFY_BODY%  [FILTERED - whipsaw]

powershell -NoProfile -WindowStyle Hidden -Command ^
  "Add-Type -AssemblyName System.Windows.Forms; ^
   $n = New-Object System.Windows.Forms.NotifyIcon; ^
   $n.Icon = [System.Drawing.SystemIcons]::Information; ^
   $n.Visible = $true; ^
   $n.ShowBalloonTip(20000, '%NOTIFY_TITLE%', '%NOTIFY_BODY%', [System.Windows.Forms.ToolTipIcon]::Info); ^
   Start-Sleep -Seconds 25; ^
   $n.Dispose()"
