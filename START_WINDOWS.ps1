$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.env')) {
  Copy-Item '.env.example' '.env'
  Write-Host 'Created .env. Add Groq and PayPal Sandbox credentials when ready.'
}
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$cfg = Join-Path $PSScriptRoot '.venv\pyvenv.cfg'
if (-not (Test-Path $py) -or -not (Test-Path $cfg)) {
  if (Test-Path '.venv') {
    throw 'Existing .venv is incomplete. Close all LAPENG Python processes and repair the environment manually; no automatic deletion will occur.'
  }
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install Astral uv first: https://docs.astral.sh/uv/'
  }
  uv python install 3.12
  if ($LASTEXITCODE -ne 0) { throw 'Unable to provision Python 3.12.' }
  uv venv --python 3.12 .venv
  if ($LASTEXITCODE -ne 0) { throw 'Unable to create a virtual environment.' }
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw 'This starter script uses uv. Install Astral uv to continue.'
}
uv pip install --python $py -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
