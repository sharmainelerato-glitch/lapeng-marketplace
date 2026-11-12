$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
Write-Host 'Checking LAPENG deployment package...' -ForegroundColor Cyan
if (-not (Test-Path 'app/main.py') -or -not (Test-Path 'render.yaml')) { throw 'Missing app/main.py or render.yaml.' }
if (Test-Path '.env') { throw 'Local .env exists in deployment folder: remove it before pushing.' }
if (Test-Path 'lapeng.sqlite3') { throw 'SQLite database exists in deployment folder: remove it before pushing.' }
python -m compileall -q app
if ($LASTEXITCODE -ne 0) { throw 'Python syntax check failed.' }
if (Get-Command node -ErrorAction SilentlyContinue) {
    node --check static/app.js
    if ($LASTEXITCODE -ne 0) { throw 'JavaScript syntax check failed.' }
} else { Write-Host 'Node unavailable; skipped JS syntax check.' -ForegroundColor Yellow }
Write-Host 'Basic local package checks passed. Verify Render deployment and buyer/provider workflows separately.' -ForegroundColor Green
