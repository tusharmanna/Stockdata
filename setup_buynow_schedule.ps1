# setup_buynow_schedule.ps1
# Registers 5 Task Scheduler jobs that run the intraday breakout scanner
# at 10:15, 11:15, 12:15, 13:15, and 14:15 ET on weekdays.
#
# Run once as Administrator:
#   powershell -ExecutionPolicy Bypass -File E:\work\Stockdata\setup_buynow_schedule.ps1

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatchFile  = Join-Path $ScriptDir "run_buynow.bat"
$TaskName   = "BuyNowScanner"

# Times to fire (ET — matches your machine's local clock if set to ET)
$FireTimes  = @("10:15", "11:15", "12:15", "13:15", "14:15")
$Weekdays   = @([DayOfWeek]::Monday, [DayOfWeek]::Tuesday, [DayOfWeek]::Wednesday,
                [DayOfWeek]::Thursday, [DayOfWeek]::Friday)

# Build one trigger per fire time
$Triggers = foreach ($t in $FireTimes) {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At $t
}

# Action: run the batch file (cmd.exe /c lets it pick up PATH properly)
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatchFile`"" `
    -WorkingDirectory $ScriptDir

# Settings: start if missed (e.g. machine was off), no idle requirement
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

# Register (overwrites existing task with same name)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $Action `
    -Trigger  $Triggers `
    -Settings $Settings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "Task '$TaskName' registered with $($FireTimes.Count) daily triggers:"
foreach ($t in $FireTimes) { Write-Host "  $t ET (Mon–Fri)" }
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  schtasks /run /tn `"$TaskName`"         # trigger manually"
Write-Host "  schtasks /query /tn `"$TaskName`" /fo LIST  # show status"
Write-Host "  schtasks /delete /tn `"$TaskName`" /f   # remove"
