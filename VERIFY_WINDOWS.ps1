$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (Get-Command uv -ErrorAction SilentlyContinue) { uv run pytest -q } else { python -m pytest -q }
Write-Host 'Open http://127.0.0.1:8000/health after starting the server to check credentials.'
