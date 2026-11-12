$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
# Run this from Task Scheduler every 15 minutes after configuring opt-in and SMTP.
# Starts a single pass; no task is created or emails sent until the owner opts in.
& '.\.venv\Scripts\python.exe' -m app.reminder_worker
