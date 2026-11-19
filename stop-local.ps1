$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'logs\server.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { exit }
$serverProcessId = [int](Get-Content -LiteralPath $pidFile)
$procInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $serverProcessId"
$expected = Join-Path $PSScriptRoot '.runtime-venv\Scripts\python.exe'
if ($procInfo -and $procInfo.ExecutablePath -eq $expected -and $procInfo.CommandLine -match 'local_server.py') {
    Stop-Process -Id $serverProcessId
    Remove-Item -LiteralPath $pidFile
    Write-Host 'Server stopped. Stop active monitoring tasks in the web page before using this script.'
}
