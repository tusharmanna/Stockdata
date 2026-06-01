# setup_tushar_schedule.ps1
# Creates a Windows Task Scheduler task to run TusharStrategy at 3:30 PM ET
# on every weekday (Mon-Fri).
#
# Run this script ONCE from PowerShell as Administrator:
#   powershell -ExecutionPolicy Bypass -File E:\work\Stockdata\setup_tushar_schedule.ps1
#
# NOTE: Task Scheduler uses your system's local clock. Your PC must be set to
#       Eastern Time (or you must adjust the trigger time below to match ET).

$taskName   = "TusharStrategy330"
$taskDescr  = "TusharStrategy: TQQQ/CASH signal at 3:30 PM ET (weekdays)"
$batFile    = "E:\work\Stockdata\run_tushar_330.bat"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action   = New-ScheduledTaskAction `
                -Execute "cmd.exe" `
                -Argument "/k `"$batFile`""   # /k keeps the window open after running

$trigger  = New-ScheduledTaskTrigger `
                -Weekly `
                -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
                -At "3:30PM"

$settings = New-ScheduledTaskSettingsSet `
                -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
                -StartWhenAvailable `
                -WakeToRun:$true

Register-ScheduledTask `
    -TaskName    $taskName `
    -Description $taskDescr `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -RunLevel    Highest `
    -Force

Write-Host ""
Write-Host "Task '$taskName' registered successfully."
Write-Host "It will run every weekday at 3:30 PM using your system clock."
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  schtasks /run /tn `"$taskName`"          # trigger manually"
Write-Host "  schtasks /delete /tn `"$taskName`" /f    # remove task"
Write-Host "  taskschd.msc                             # open Task Scheduler UI"
Write-Host ""
