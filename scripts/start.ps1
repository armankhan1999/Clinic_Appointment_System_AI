<#
.SYNOPSIS
    Starts the clinic stack on this PC: staff API, Telegram bot with its reminder scheduler, and the dashboard (E7-S6).

.DESCRIPTION
    Builds the dashboard when needed, starts each part in the background, and waits until the API is ready,
    the dashboard answers and the scheduler has run once. Gives up after -TimeoutSeconds and stops what it started.
    Output goes to logs\<part>.out.log / .err.log; process ids to logs\stack.pids. Stop with scripts\stop.ps1.

.PARAMETER WebPort
    Port for the dashboard (default 3000). Use another one if 3000 is taken.

.PARAMETER NoBot
    Start the API and dashboard only (no Telegram polling, no reminder scheduler).

.PARAMETER Rebuild
    Rebuild the dashboard even when an up-to-date build exists.

.PARAMETER Dev
    Live development: the dashboard runs `next dev`, so frontend edits appear in the browser at once
    (no build). After backend edits run scripts\restart.ps1 -Part api (or bot). Not for demos or production.

.EXAMPLE
    pwsh scripts/start.ps1 -WebPort 3100

.EXAMPLE
    pwsh scripts/start.ps1 -WebPort 3100 -Dev
#>
[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)][int]$WebPort = 3000,
    [switch]$NoBot,
    [switch]$Rebuild,
    [switch]$Dev,
    [ValidateRange(30, 600)][int]$TimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'apps/backend'
$web = Join-Path $root 'apps/web'
$logs = Join-Path $root 'logs'
$pidFile = Join-Path $logs 'stack.pids'
$envFile = Join-Path $root '.env'

if (Test-Path $pidFile) {
    throw 'The stack looks like it is already running (logs\stack.pids exists). Run scripts\stop.ps1 first.'
}
foreach ($tool in 'uv', 'node', 'npm') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not installed or not on PATH." }
}
if (-not (Test-Path $envFile)) { throw '.env is missing. Copy .env.example to .env and fill it in (see README).' }
if (-not (Test-Path (Join-Path $web 'node_modules'))) { throw 'Dashboard dependencies are missing. Run: Set-Location apps/web; npm ci' }

$apiPortLine = Get-Content $envFile | Where-Object { $_ -match '^\s*API_PORT\s*=\s*\d+' } | Select-Object -Last 1
$apiPort = if ($apiPortLine) { [int](($apiPortLine -split '=', 2)[1].Trim()) } else { 8000 }
foreach ($port in $apiPort, $WebPort) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Free it, or pick another port (API_PORT in .env, -WebPort here)."
    }
}

New-Item -ItemType Directory -Force -Path $logs | Out-Null
$clock = [System.Diagnostics.Stopwatch]::StartNew()

# The API port is baked into the dashboard build (next.config rewrites), so rebuild when it changes.
$buildMarker = Join-Path $web '.next/clinic-api-port'
$builtFor = if (Test-Path $buildMarker) { (Get-Content $buildMarker -Raw).Trim() } else { '' }
$env:API_PORT = "$apiPort"  # read by next.config for the /api/v1 rewrite (dev server and build)
if (-not $Dev -and ($Rebuild -or -not (Test-Path (Join-Path $web '.next/BUILD_ID')) -or $builtFor -ne "$apiPort")) {
    Write-Host "Building the dashboard for API port $apiPort ..."
    $env:API_PORT = "$apiPort"
    Push-Location $web
    try {
        npm run build *> (Join-Path $logs 'web-build.log')
        if ($LASTEXITCODE -ne 0) { throw "Dashboard build failed; see logs\web-build.log." }
    }
    finally { Pop-Location }
    Set-Content -Path $buildMarker -Value "$apiPort" -NoNewline
}

function Start-Part([string]$Name, [string]$Directory, [string]$File, [string[]]$Arguments) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -WorkingDirectory $Directory -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "$Name.out.log") `
        -RedirectStandardError (Join-Path $logs "$Name.err.log")
    Add-Content -Path $pidFile -Value "$Name=$($process.Id)"
    $process
}

function Stop-Started {
    if (Test-Path $pidFile) { & (Join-Path $PSScriptRoot 'stop.ps1') }
}

function Test-Http([string]$Url) {
    try { (Invoke-WebRequest -Uri $Url -TimeoutSec 10 -SkipHttpErrorCheck).StatusCode -eq 200 }
    # Refused connections and probe timeouts (a dev server compiling its first page) both mean 'not ready yet'.
    catch [System.Net.Http.HttpRequestException], [System.Threading.Tasks.TaskCanceledException], [System.TimeoutException] {
        $false
    }
}

$uv = (Get-Command uv).Source
$node = (Get-Command node).Source
$parts = [ordered]@{}
$parts.api = Start-Part 'api' $backend $uv @('run', 'clinic-api')
if (-not $NoBot) { $parts.bot = Start-Part 'bot' $backend $uv @('run', 'clinic-bot') }
$nextMode = if ($Dev) { 'dev' } else { 'start' }
$parts.web = Start-Part 'web' $web $node @('node_modules/next/dist/bin/next', $nextMode, '-p', "$WebPort")

$checks = [ordered]@{
    api = { Test-Http "http://127.0.0.1:$apiPort/readyz" }
    web = { Test-Http "http://localhost:$WebPort/login" }
}
if (-not $NoBot) {
    $botLog = Join-Path $logs 'bot.out.log'
    # The first reminder run (15 s after start) proves both the bot process and its scheduler are live.
    $checks.bot = { (Test-Path $botLog) -and (Select-String -Path $botLog -Pattern '"scheduler_heartbeat"' -Quiet) }
}

$ready = @{}
try {
while ($clock.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
    foreach ($name in @($checks.Keys)) {
        if ($ready.ContainsKey($name)) { continue }
        if ($parts[$name].HasExited) {
            Stop-Started
            throw "The $name process exited early; see logs\$name.err.log and logs\$name.out.log."
        }
        if (& $checks[$name]) {
            $ready[$name] = [math]::Round($clock.Elapsed.TotalSeconds, 1)
            Write-Host ("{0,-4} ready after {1} s" -f $name, $ready[$name])
        }
    }
    if ($ready.Count -eq $checks.Count) { break }
    Start-Sleep -Seconds 2
}
}
catch {
    # Never leave half-started servers behind.
    Stop-Started
    throw
}

if ($ready.Count -ne $checks.Count) {
    $missing = @($checks.Keys | Where-Object { -not $ready.ContainsKey($_) }) -join ', '
    Stop-Started
    throw "Not ready within $TimeoutSeconds s: $missing. See the logs in $logs."
}

Write-Host ''
Write-Host ("Stack up in {0:N1} s{1}." -f $clock.Elapsed.TotalSeconds, $(if ($Dev) { ' in live development mode' } else { '' }))
Write-Host "  Dashboard: http://localhost:$WebPort"
Write-Host "  API:       http://127.0.0.1:$apiPort (health: /healthz, readiness: /readyz)"
if (-not $NoBot) { Write-Host '  Bot:       long polling, reminder jobs every 5 min, outbox every 1 min' }
Write-Host '  Stop with: pwsh scripts/stop.ps1'
