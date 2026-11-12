param([string]$Project = (Get-Location).Path, [string]$Zip = "$HOME\Downloads\LAPENG_Render_Free_Demo.zip")
$ErrorActionPreference = 'Stop'
if (-not (Test-Path (Join-Path $Project 'app\main.py'))) { throw "Not a LAPENG deployment project: $Project" }
if (-not (Test-Path $Zip)) { throw "Download ZIP first: $Zip" }
$stage = Join-Path $env:TEMP ('lapeng_render_free_' + [guid]::NewGuid().ToString('N'))
$backup = Join-Path $HOME ('Downloads\LAPENG_Free_Backup_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
try {
  Expand-Archive -LiteralPath $Zip -DestinationPath $stage
  $source = Join-Path $stage 'LAPENG_Render_Free_Demo'
  foreach ($rel in @('render.yaml','FREE_RENDER_DEPLOY.md','static\index.html','static\demo-notice.css')) {
    $from = Join-Path $source $rel
    $target = Join-Path $Project $rel
    if (-not (Test-Path $from)) { throw "Missing update file: $rel" }
    if (Test-Path $target) { $backupName = $rel.Replace('\','_'); Copy-Item -LiteralPath $target -Destination (Join-Path $backup $backupName) -Force }
    Copy-Item -LiteralPath $from -Destination $target -Force
  }
  Write-Host 'Render Free demo config installed (no Git push performed).' -ForegroundColor Green
  Write-Host "Backup folder: $backup"
  Write-Host 'Review: git diff --stat; git diff render.yaml; git status'
  Write-Host 'Read FREE_RENDER_DEPLOY.md before creating the Render service.'
} finally { if (Test-Path $stage) { Remove-Item $stage -Recurse -Force } }

