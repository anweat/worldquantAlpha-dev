# wqbus interactive console.
#
# A simple REPL that wraps the most common wqbus subcommands so you don't have
# to retype the long python/PYTHONPATH prefix every time. Type `help` inside.
param([string]$Dataset = "usa_top3000")

$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"

function Invoke-Wqbus {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Args)
    & python -m wq_bus.cli --dataset $script:Dataset @Args
}

function Show-Help {
    @"
=== wqbus console (dataset=$Dataset) ===
  status                Show queue/AI/submitted snapshot
  resume                Catchup: re-emit pending events
  generate [N] [hint]   Trigger alpha generation (default N=4)
  flush                 Flush submission queue
  submit-eligible       Re-queue IS-eligible alphas not yet submitted
  summarize             Force doc summarization
  trace recent [N]      Show N recent traces (default 5)
  trace <id> [--full]   Show full activity chain for a trace_id
  trace alpha <id>      Lookup trace from alpha_id
  cap reset             Backdate today's ai_calls (clear daily cap)
  daemon                Run daemon in foreground (Ctrl-C to stop)
  start                 Launch daemon detached in background
  stop                  Stop background daemon
  log [N]               Tail N lines (default 30) of logs\daemon.log
  dataset <tag>         Switch active dataset
  emit <TOPIC> [json]   Emit raw event onto bus
  q | quit | exit       Leave console
"@ | Write-Host
}

Show-Help
while ($true) {
    Write-Host ""
    $line = Read-Host "wqbus[$Dataset]>"
    if (-not $line) { continue }
    $parts = $line.Trim().Split(" ", 2)
    $cmd   = $parts[0].ToLower()
    $rest  = if ($parts.Length -gt 1) { $parts[1] } else { "" }

    switch ($cmd) {
        { $_ -in @("q","quit","exit") } { return }
        "help"   { Show-Help }
        "status" { Invoke-Wqbus admin status }
        "resume" { Invoke-Wqbus resume }
        "flush"  { Invoke-Wqbus submit-flush }
        "submit-eligible" { Invoke-Wqbus admin submit-eligible }
        "summarize" { Invoke-Wqbus summarize }
        "generate" {
            $n = 4; $hint = ""
            if ($rest) {
                $rp = $rest.Split(" ", 2)
                if ($rp[0] -match '^\d+$') { $n = [int]$rp[0]; $hint = if ($rp.Length -gt 1) { $rp[1] } else { "" } }
                else { $hint = $rest }
            }
            Invoke-Wqbus generate -n $n --hint $hint
        }
        "trace" {
            $rp = $rest.Split(" ")
            if ($rp[0] -eq "recent") {
                $n = if ($rp.Length -gt 1 -and $rp[1] -match '^\d+$') { $rp[1] } else { "5" }
                Invoke-Wqbus trace --recent $n
            } elseif ($rp[0] -eq "alpha") {
                Invoke-Wqbus trace --alpha $rp[1]
            } else {
                Invoke-Wqbus trace @rp
            }
        }
        "cap" {
            if ($rest -match "reset") { Invoke-Wqbus admin reset-ai-cap --yes }
            else { Write-Host "usage: cap reset" }
        }
        "daemon" { Invoke-Wqbus daemon }
        "start"  { & "$PSScriptRoot\start.ps1" -Dataset $Dataset -Detach }
        "stop"   { & "$PSScriptRoot\stop.ps1" }
        "log" {
            $n = if ($rest -match '^\d+$') { [int]$rest } else { 30 }
            if (Test-Path "logs\daemon.log") { Get-Content -Tail $n "logs\daemon.log" }
            else { Write-Host "no logs\daemon.log yet" }
        }
        "dataset" {
            if ($rest) { $Dataset = $rest.Trim(); Write-Host "switched to $Dataset" }
            else       { Write-Host "current dataset: $Dataset" }
        }
        "emit" {
            $rp = $rest.Split(" ", 2)
            if ($rp.Length -ge 2) { Invoke-Wqbus emit $rp[0] --json $rp[1] }
            elseif ($rp.Length -eq 1) { Invoke-Wqbus emit $rp[0] }
            else { Write-Host "usage: emit <TOPIC> [json]" }
        }
        default { Write-Host "unknown: $cmd  (try 'help')" }
    }
}
