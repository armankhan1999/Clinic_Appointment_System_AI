<#
.SYNOPSIS
    Restarts one part of the stack that scripts\start.ps1 started: the API or the Telegram bot.

.DESCRIPTION
    Use it after backend changes, for example in live development (-Dev), where the dashboard already
    updates by itself. Stops the part's whole process tree, starts it again with the same logs, waits until
    it is healthy (API: /readyz; bot: first scheduler heartbeat) and updates logs\stack.pids.

.EXAMPLE
    pwsh scripts/restart.ps1 -Part api
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('api', 'bot')][string]$Part,
    [ValidateRange(10, 300)][int]$TimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'apps/backend'
$logs = Join-Path $root 'logs'
$pidFile = Join-Path $logs 'stack.pids'
if (-not (Test-Path $pidFile)) { throw 'The stack is not running (logs\stack.pids is missing). Use scripts\start.ps1.' }

$entries = Get-Content $pidFile
$line = $entries | Where-Object { $_ -like "$Part=*" } | Select-Object -First 1
if (-not $line) { throw "$Part is not part of the running stack (was it started with -NoBot?)." }
$oldId = ($line -split '=', 2)[1]
if (Get-Process -Id ([int]$oldId) -ErrorAction SilentlyContinue) { taskkill /PID $oldId /T /F | Out-Null }

$command = if ($Part -eq 'api') { 'clinic-api' } else { 'clinic-bot' }
$process = Start-Process -FilePath (Get-Command uv).Source -ArgumentList @('run', $command) -WorkingDirectory $backend `
    -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs "$Part.out.log") `
    -RedirectStandardError (Join-Path $logs "$Part.err.log")
$entries -replace "^$Part=\d+$", "$Part=$($process.Id)" | Set-Content $pidFile

$envFile = Join-Path $root '.env'
$apiPortLine = Get-Content $envFile | Where-Object { $_ -match '^\s*API_PORT\s*=\s*\d+' } | Select-Object -Last 1
$apiPort = if ($apiPortLine) { [int](($apiPortLine -split '=', 2)[1].Trim()) } else { 8000 }

$clock = [System.Diagnostics.Stopwatch]::StartNew()
while ($clock.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
    if ($process.HasExited) { throw "$Part exited; see logs\$Part.err.log and logs\$Part.out.log." }
    $ready = if ($Part -eq 'api') {
        try { (Invoke-WebRequest "http://127.0.0.1:$apiPort/readyz" -TimeoutSec 10 -SkipHttpErrorCheck).StatusCode -eq 200 }
        catch [System.Net.Http.HttpRequestException], [System.Threading.Tasks.TaskCanceledException], [System.TimeoutException] { $false }
    }
    else {
        Select-String -Path (Join-Path $logs 'bot.out.log') -Pattern '"scheduler_heartbeat"' -Quiet
    }
    if ($ready) {
        Write-Host ("{0} restarted and ready after {1:N1} s (pid {2})" -f $Part, $clock.Elapsed.TotalSeconds, $process.Id)
        return
    }
    Start-Sleep -Seconds 2
}
throw "$Part did not become ready within $TimeoutSeconds s; see logs\$Part.out.log."
