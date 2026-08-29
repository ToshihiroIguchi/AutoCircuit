# Run one stage of the AutoEIS round end to end, unattended.
#
# The two producers must not run at the same time -- both saturate the machine -- so this runs
# them in sequence and then scores whatever pairs exist. Every step is resumable by re-issuing
# the identical command, so this script is safe to kill and restart: it costs at most the one run
# that was in flight.
#
# Launch it detached, so that it outlives the shell that started it:
#
#   Start-Process powershell -ArgumentList "-NoProfile","-File",
#     "C:\Users\toshi\python\AutoCircuit\benchmarks\autoeis_round\run_round.ps1","-MaxSeeds","5" `
#     -WindowStyle Hidden
#
# Note on reading the interim report: scoring a partial round is fine, but the stopping rule
# (arena.py, and section 1.6 of docs/AUTOEIS_COMPARISON.md) is that the round stops on machine
# time and never because a result looked significant. Looking is allowed; stopping *because* of
# what was seen is not.

param(
    [int]$MaxSeeds = 5,
    [string]$Arena = "benchmarks/autoeis_round/arena_c",
    [int]$Workers = 6,
    [int]$Retries = 3
)

$ErrorActionPreference = "Continue"
$repo = "C:\Users\toshi\python\AutoCircuit"
# Absolute paths for both interpreters. A hidden -NoProfile process does not necessarily resolve
# `python` from PATH, and when it cannot the call fails instantly with $LASTEXITCODE unset, which
# looks exactly like a run that finished -- the retry loop then burns through its attempts in one
# second and moves on. Measured, the first time this script was launched.
$py = "C:\Users\toshi\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"
$venv = "C:\Users\toshi\python\autoeis-env\Scripts\python.exe"
$out = Join-Path $repo "benchmarks\autoeis_round"
Set-Location $repo
$env:PYTHONPATH = "$repo\src;$repo\benchmarks\autoeis_round"

function Say($message) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path (Join-Path $out "round.log") -Value "$stamp  $message" -Encoding utf8
}

Say "=== round start: max-seeds $MaxSeeds, arena $Arena ==="

# --- 1. this project's search -------------------------------------------------------------
for ($i = 1; $i -le $Retries; $i++) {
    Say "AutoCircuit producer, attempt $i"
    & $py benchmarks/autoeis_round/run_autocircuit.py --arena $Arena --max-seeds $MaxSeeds --workers $Workers *>> (Join-Path $out "run_ac.log")
    if ($LASTEXITCODE -eq 0) { Say "AutoCircuit producer finished"; break }
    Say "AutoCircuit producer exited '$LASTEXITCODE'; retrying (it resumes where it stopped)"
    Start-Sleep -Seconds 30
}

# --- 2. AutoEIS, in its own environment ---------------------------------------------------
for ($i = 1; $i -le $Retries; $i++) {
    Say "AutoEIS producer, attempt $i"
    & $venv benchmarks/autoeis_round/run_autoeis.py --arena $Arena --max-seeds $MaxSeeds *>> (Join-Path $out "run_ae.log")
    if ($LASTEXITCODE -eq 0) { Say "AutoEIS producer finished"; break }
    Say "AutoEIS producer exited '$LASTEXITCODE'; retrying (it resumes where it stopped)"
    Start-Sleep -Seconds 30
}

# --- 3. score whatever is paired -----------------------------------------------------------
Say "scoring"
& $py benchmarks/autoeis_round/score.py --arena $Arena --out (Join-Path $Arena "report.json") *>> (Join-Path $out "score.log")
Say "=== round done (exit $LASTEXITCODE) ==="
