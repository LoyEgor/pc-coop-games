# Coop-hunter overnight launcher
#
# Usage: open PowerShell (NORMAL user -- admin not needed), navigate to repo, run:
#     .\run-coop-hunter.ps1
#
# Or double-click is fine if PowerShell scripts are allowed.
# If you get "execution policy" error, run ONCE in PowerShell:
#     Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#
# To stop: Ctrl+C. The skill state on disk is persistent -- restart any time.

$ErrorActionPreference = "Continue"

$repoRoot = $PSScriptRoot
$logFile = Join-Path $repoRoot "coop-hunter.log"
$progressFile = Join-Path $repoRoot ".claude\skills\coop-hunter\state\progress.json"
$addedTsv = Join-Path $repoRoot ".claude\skills\coop-hunter\state\added.tsv"

Set-Location $repoRoot

Write-Host "================================================================"
Write-Host "  coop-hunter overnight runner"
Write-Host "================================================================"
Write-Host "  Started:    $(Get-Date)"
Write-Host "  Repo:       $repoRoot"
Write-Host "  Log file:   $logFile"
Write-Host "  Progress:   $progressFile"
Write-Host "  Ctrl+C to stop. State is persistent -- safe to restart later."
Write-Host "================================================================"
Write-Host ""

$goalPrompt = @'
/goal Run the coop-hunter skill from .claude/skills/coop-hunter/ to expand data.js with new PC co-op games.

Strict rules (read SKILL.md and classification.md before starting):

1. Process candidates sequentially from sources.json in the order defined. Sleep 1.5s between Steam API calls. Process ONLY 3-5 candidates per turn before returning control.

2. Persist progress to state/progress.json AFTER EVERY game added or skipped. Append to state/added.tsv and state/skipped.tsv. This is non-negotiable -- if you skip persistence and crash, work is lost.

3. Run a validation pass (spawn a fresh general-purpose Agent) every 50 added games. Log failures to state/validation-fails.tsv. Do NOT auto-correct -- only log.

4. NEVER ASK QUESTIONS. For every decision, use the deterministic rules in classification.md. If a candidate is genuinely ambiguous, append to state/skipped.tsv with reason "ambiguous" and continue. The user is asleep -- there is nobody to answer.

5. If a tool call fails, retry once with 5s extra sleep. On second failure, log to skipped and continue. Do NOT halt for transient errors.

6. Do NOT modify app.js, index.html, or styles.css. ONLY modify data.js (via scripts/append_entry.py, never by hand-editing).

7. Do NOT create new files outside .claude/skills/coop-hunter/state/ and data.js. Do NOT touch git (no commits during the run -- user will review in the morning).

Continue until ANY of:
(a) all 9 sources are marked completed in progress.json,
(b) progress.json shows done=true,
(c) you have added 300 new games this session.

Output a single line summary every 10 additions: "[N added] [skip: K] [src: source_id] [last: <title>]"

The user is offline overnight. Make autonomous, conservative, rule-based decisions. When in doubt, SKIP rather than add -- quality > volume.
'@

$maxRestarts = 20
$restarts = 0
$initialAdded = 0
if (Test-Path $progressFile) {
  $p = Get-Content $progressFile -Raw | ConvertFrom-Json
  $initialAdded = $p.added_count
}
Write-Host "Initial added_count from progress.json: $initialAdded"
Write-Host ""

while ($true) {
  Write-Host ""
  Write-Host "[$(Get-Date)] -- Starting claude (run #$($restarts + 1)) --" -ForegroundColor Yellow
  Write-Host ""

  # Run claude in headless mode with autonomous permissions
  claude --dangerously-skip-permissions -p $goalPrompt 2>&1 | Tee-Object -FilePath $logFile -Append

  # After claude exits, check progress
  if (-not (Test-Path $progressFile)) {
    Write-Host "[$(Get-Date)] WARNING: progress.json missing after run. Stopping." -ForegroundColor Red
    break
  }

  $progress = Get-Content $progressFile -Raw | ConvertFrom-Json
  Write-Host ""
  Write-Host "[$(Get-Date)] Run finished. added=$($progress.added_count) skipped=$($progress.skipped_count) done=$($progress.done)" -ForegroundColor Cyan

  if ($progress.done) {
    Write-Host ""
    Write-Host "[$(Get-Date)] SKILL MARKED DONE." -ForegroundColor Green
    break
  }

  $restarts++
  if ($restarts -ge $maxRestarts) {
    Write-Host "[$(Get-Date)] Hit max restarts ($maxRestarts). Stopping." -ForegroundColor Red
    break
  }

  Write-Host "[$(Get-Date)] Process exited but skill not done. Restarting in 30s..." -ForegroundColor Yellow
  Start-Sleep 30
}

Write-Host ""
Write-Host "================================================================"
Write-Host "  Finished at $(Get-Date)"
Write-Host "================================================================"
if (Test-Path $progressFile) {
  $final = Get-Content $progressFile -Raw | ConvertFrom-Json
  $delta = $final.added_count - $initialAdded
  Write-Host "  Added this session:   $delta"
  Write-Host "  Total added:          $($final.added_count)"
  Write-Host "  Skipped total:        $($final.skipped_count)"
  Write-Host "  Sources completed:    $($final.completed_sources -join ', ')"
}
Write-Host ""
Write-Host "Review:"
Write-Host "  Log:               $logFile"
Write-Host "  Added games:       $addedTsv"
Write-Host "  Skipped:           $repoRoot\.claude\skills\coop-hunter\state\skipped.tsv"
Write-Host "  Validation fails:  $repoRoot\.claude\skills\coop-hunter\state\validation-fails.tsv"
Write-Host ""
Write-Host "Don't forget to git diff / git commit data.js if you're happy with the additions."
