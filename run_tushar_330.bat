@echo off
title TusharStrategy -- 3:30 PM Signal
cd /d E:\work\Stockdata
echo.
echo ================================================================
echo  TusharStrategy  --  Running at %date% %time%
echo ================================================================
echo.
python tushar_strategy.py
echo.
echo ================================================================
echo  Done. Review the signal above and act before 4:00 PM ET.
echo ================================================================
echo.
pause
