@echo off
REM Test runner for EnterOrdersIB.py unit tests

echo ========================================
echo Running EnterOrdersIB.py Unit Tests
echo ========================================
echo.

python test_EnterOrdersIB.py -v

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo All tests passed!
    echo ========================================
) else (
    echo.
    echo ========================================
    echo Tests FAILED
    echo ========================================
    exit /b 1
)

pause
