# Stop a detached daemon started with start.ps1 -Detach.
$ErrorActionPreference = "SilentlyContinue"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
if (-not (Test-Path "logs\daemon.pid")) {
    Write-Host "no logs\daemon.pid — daemon not running (or started in foreground)"
    exit 0
}
$pid_ = Get-Content "logs\daemon.pid" | Select-Object -First 1
$pid_ = [int]$pid_
$proc = Get-Process -Id $pid_ -ErrorAction SilentlyContinue
if ($null -eq $proc) {
    Write-Host "pid $pid_ is not running; clearing pidfile"
    Remove-Item "logs\daemon.pid"
    exit 0
}
Stop-Process -Id $pid_
Write-Host "[stop] sent stop to pid $pid_"
Remove-Item "logs\daemon.pid"
