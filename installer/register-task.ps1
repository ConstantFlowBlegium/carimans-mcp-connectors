# Carimans MCP Connectors - Register Scheduled Task
# Copies updater.ps1 to a stable location and registers a Windows Scheduled Task

$ErrorActionPreference = "Stop"

$TaskName = "CarimansAIUpdater"
$StablePath = "$env:APPDATA\Carimans"
$UpdaterSource = Join-Path $PSScriptRoot "updater.ps1"
$UpdaterDest = Join-Path $StablePath "updater.ps1"

# 1. Copy updater.ps1 to stable location
if (-not (Test-Path $StablePath)) {
    New-Item -ItemType Directory -Path $StablePath -Force | Out-Null
}
Copy-Item -Path $UpdaterSource -Destination $UpdaterDest -Force
Write-Host "Updater script copied to $UpdaterDest"

# 2. Build the scheduled task action
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -NonInteractive -File `"$UpdaterDest`""

# 3. Build triggers: on logon + daily at 9:00 AM
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn
$triggerDaily = New-ScheduledTaskTrigger -Daily -At "09:00"

# 4. Task settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

# 5. Register or update
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task '$TaskName'"
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggerLogon, $triggerDaily `
    -Settings $settings `
    -Description "Auto-updates Carimans MCP server config for Claude Desktop" `
    -RunLevel Limited | Out-Null

Write-Host "Scheduled task '$TaskName' registered successfully"
Write-Host "  - Trigger 1: On user logon"
Write-Host "  - Trigger 2: Daily at 9:00 AM"
Write-Host "  - Script: $UpdaterDest"
