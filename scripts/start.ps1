# wqbus daemon launcher.
#
# Starts the bus daemon in the foreground (or background with -Detach).
# Usage:
#   .\scripts\start.ps1                       # foreground daemon
#   .\scripts\start.ps1 -Dataset usa_top3000
#   .\scripts\start.ps1 -DryRun
#   .\scripts\start.ps1 -Detach               # background, logs to logs\daemon.log
param(
    [string]$Dataset = "usa_top3000",
    [int]$TargetSubmitted = 4,
    [int]$AutoGenN = 4,
    [int]$IdleSecs = 120,
    [int]$AutoGenIdleSecs = 900,
    [switch]$DryRun,
    [switch]$NoAutoGen,
    [switch]$NoAutoResume,
    [switch]$Detach
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"

$argList = @("-m", "wq_bus.cli", "--dataset", $Dataset)
if ($DryRun) { $argList += "--dry-run" }
$argList += @("daemon",
    "--idle-secs", "$IdleSecs",
    "--auto-gen-n", "$AutoGenN",
    "--auto-gen-idle-secs", "$AutoGenIdleSecs",
    "--target-submitted", "$TargetSubmitted")
if ($NoAutoGen)    { $argList += "--no-auto-gen" }
if ($NoAutoResume) { $argList += "--no-auto-resume" }

if (-not (Test-Path "logs")) { New-Item -ItemType Directory logs | Out-Null }

# Pre-flight: ensure BRAIN session is valid (auto-login from .state/credentials.json if needed)
Write-Host "[start] checking BRAIN session..."
& python -m wq_bus.cli login 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "[start] login failed — aborting (set credentials in .state/credentials.json or env vars)" -ForegroundColor Red
    exit 1
}

if ($Detach) {
    $log = "logs\daemon.log"
    $err = "logs\daemon.err"
    $proc = Start-Process -FilePath "python" -ArgumentList $argList `
        -RedirectStandardOutput $log -RedirectStandardError $err `
        -WindowStyle Hidden -PassThru
    "$($proc.Id)" | Out-File -Encoding ascii "logs\daemon.pid"
    Write-Host "[start] daemon detached, pid=$($proc.Id) log=$log"
    Write-Host "       stop with:  .\scripts\stop.ps1"
    Write-Host "       follow log: Get-Content -Tail 30 -Wait $log"
} else {
    Write-Host "[start] python $($argList -join ' ')"
    & python @argList
}
