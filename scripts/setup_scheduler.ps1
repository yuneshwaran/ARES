# AresJobSearch — Windows Task Scheduler Setup
# Run PowerShell as Administrator (or omit -RunLevel Highest for current-user tasks)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectDir "venv\Scripts\python.exe"
$MainScript = Join-Path $ProjectDir "main.py"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Virtual environment Python not found at $PythonExe. Create venv and install requirements first."
}

$CommonSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

# 1. Job Discovery + Scoring — every 6 hours
$SearchAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$MainScript`" run all" `
    -WorkingDirectory $ProjectDir

$SearchTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Hours 6) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

Register-ScheduledTask `
    -TaskName "AresJobSearch - Discovery Pipeline" `
    -Action $SearchAction `
    -Trigger $SearchTrigger `
    -Settings $CommonSettings `
    -Description "Run AresJobSearch discovery, scoring, tailoring, and email tracking every 6 hours" `
    -Force | Out-Null

# 2. Email Tracking — every 1 hour
$EmailAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$MainScript`" check-email" `
    -WorkingDirectory $ProjectDir

$EmailTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(10) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

Register-ScheduledTask `
    -TaskName "AresJobSearch - Email Tracker" `
    -Action $EmailAction `
    -Trigger $EmailTrigger `
    -Settings $CommonSettings `
    -Description "Check Gmail for recruiter updates every hour and update Excel tracker" `
    -Force | Out-Null

Write-Host "Scheduled tasks created successfully!" -ForegroundColor Green
Write-Host "  - AresJobSearch - Discovery Pipeline (every 6 hours)"
Write-Host "  - AresJobSearch - Email Tracker (every 1 hour)"
Write-Host "Manage them in Task Scheduler: taskschd.msc" -ForegroundColor Cyan
