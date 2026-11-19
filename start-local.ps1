$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PSScriptRoot '.browsers'
$existing = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($existing) { Write-Host 'Port 8765 is already in use. Open http://127.0.0.1:8765'; exit }
$process = Start-Process -FilePath (Join-Path $PSScriptRoot '.runtime-venv\Scripts\python.exe') -ArgumentList '-u','local_server.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'logs\server.out.log') -RedirectStandardError (Join-Path $PSScriptRoot 'logs\server.err.log') -PassThru
$process.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'logs\server.pid')
Write-Host 'Started local monitor: http://127.0.0.1:8765'
