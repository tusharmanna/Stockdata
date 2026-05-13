# Registers a Task Scheduler job that runs the Whitelight signal generator
# every weekday at 3:45 PM ET (15 minutes before market close).
#
# Run once as Administrator:
#   powershell -ExecutionPolicy Bypass -File E:\work\Stockdata\setup_whitelight_schedule.ps1

$action = New-ScheduledTaskAction -Execute 'E:\work\Stockdata\run_whitelight.bat'

$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At '3:45PM'

# StartWhenAvailable: catches up if the PC was asleep at 3:45.
# ExecutionTimeLimit: kill after 10 minutes if it hangs.
# RunOnlyIfNetworkAvailable: needs internet for yfinance download.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName 'WhitelightSignal' `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force

Write-Host "Task 'WhitelightSignal' registered. Runs Mon-Fri at 3:45 PM." -ForegroundColor Green
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  schtasks /run /tn WhitelightSignal     -- trigger now"
Write-Host "  schtasks /delete /tn WhitelightSignal /f  -- remove task"
Write-Host "  taskschd.msc                           -- open Task Scheduler UI"
