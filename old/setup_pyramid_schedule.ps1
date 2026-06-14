# Register QQQ pyramid signal check to run Mon-Fri at 3:30 PM ET
# Run this once as Administrator: powershell -ExecutionPolicy Bypass -File .\setup_pyramid_schedule.ps1

$action = New-ScheduledTaskAction -Execute 'python' `
    -Argument 'E:\work\Stockdata\qqq_pyramid_signal.py' `
    -WorkingDirectory 'E:\work\Stockdata'

$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At 3:30PM

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName "StockDataPyramidSignal" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force

Write-Host "Scheduled task 'StockDataPyramidSignal' registered - runs Mon-Fri at 3:30 PM ET"
Write-Host "View/manage in Task Scheduler or run: schtasks /query /tn StockDataPyramidSignal"
Write-Host "Manual test: python qqq_pyramid_signal.py"
