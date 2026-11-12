param([Parameter(Mandatory=$true)][string]$Project)
$ErrorActionPreference='Stop'
$source=Split-Path -Parent $MyInvocation.MyCommand.Path
$destination=[IO.Path]::GetFullPath($Project)
if (!(Test-Path -LiteralPath "$destination\app\main.py")) { throw "This doesn't look like the existing LAPENG project: $destination" }
$backup=Join-Path $destination ('release_backup_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach($folder in @('app','static','tests')) {
  if(Test-Path -LiteralPath (Join-Path $destination $folder)) {Copy-Item -LiteralPath (Join-Path $destination $folder) -Destination $backup -Recurse -Force}
}
foreach($folder in @('app','static','tests','docs')) {
  Copy-Item -Path (Join-Path $source $folder) -Destination $destination -Recurse -Force
}
foreach($file in @('.env.example','requirements.txt','render.yaml','README.md','RELEASE_README.md')) {
  Copy-Item -LiteralPath (Join-Path $source $file) -Destination (Join-Path $destination $file) -Force
}
Write-Host "LAPENG release files installed. Original .env, database and uploads were not changed." -ForegroundColor Green
Write-Host "Backup of previous code: $backup"
Write-Host "Restart the existing server, then refresh the browser with Ctrl+F5."
