$action  = New-ScheduledTaskAction -Execute 'E:\work\Stockdata\run_daily.bat'
$trigger = New-ScheduledTaskTrigger -Weekly `
               -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
               -At 8PM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask `
    -TaskName "StockDataDaily" `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force
