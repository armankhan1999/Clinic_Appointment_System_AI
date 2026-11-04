<#
.SYNOPSIS
    Stops the processes that scripts\start.ps1 started (listed in logs\stack.pids), including their child processes.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$pidFile = Join-Path (Split-Path -Parent $PSScriptRoot) 'logs/stack.pids'
if (-not (Test-Path $pidFile)) {
    Write-Host 'Nothing to stop: logs\stack.pids does not exist.'
    return
}

foreach ($line in Get-Content $pidFile) {
    $name, $id = $line -split '=', 2
    if (-not ($id -match '^\d+$')) { continue }
    if (Get-Process -Id ([int]$id) -ErrorAction SilentlyContinue) {
        # uv and node start child processes; /T stops the whole tree.
        taskkill /PID $id /T /F | Out-Null
        Write-Host "stopped $name (pid $id)"
    }
    else {
        Write-Host "$name (pid $id) was not running"
    }
}
Remove-Item $pidFile
