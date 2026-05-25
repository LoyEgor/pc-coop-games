# Coop-hunter overnight launcher (INTERACTIVE mode)
#
# Runs Claude Code in interactive mode so you SEE the chat live in this terminal.
# Permission prompts are bypassed. Auto-restarts if claude exits before the skill
# marks itself done. The single /goal prompt is sent automatically as the first
# message -- you don't need to type or paste anything.
#
# Usage:
#   1. Open PowerShell (normal user, NOT admin).
#   2. cd "C:\Users\loyeg\OneDrive\Documents\Games for Two 2"
#   3. .\run-coop-hunter.ps1
#   4. Watch. Go to sleep. Read in the morning.
#
# If you see an "execution policy" error, run ONCE:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

$ErrorActionPreference = "Continue"

$repoRoot = $PSScriptRoot
$progressFile = Join-Path $repoRoot ".claude\skills\coop-hunter\state\progress.json"
$transcript = Join-Path $repoRoot "coop-hunter-transcript.log"

Set-Location $repoRoot

# Locate the claude CLI. Try PATH first, then known npm install location.
$claudeCmd = $null
$onPath = Get-Command claude -ErrorAction SilentlyContinue
if ($onPath) {
  $claudeCmd = $onPath.Source
} else {
  $candidate = Join-Path $env:APPDATA "npm\claude.cmd"
  if (Test-Path $candidate) {
    $claudeCmd = $candidate
    # Also add to PATH for this session so child processes find it.
    $env:Path = "$($env:APPDATA)\npm;$env:Path"
  }
}

if (-not $claudeCmd) {
  Write-Host "ERROR: claude CLI not found. Tried PATH and $env:APPDATA\npm\claude.cmd." -ForegroundColor Red
  Write-Host "Install with: npm install -g @anthropic-ai/claude-code" -ForegroundColor Yellow
  exit 1
}
Write-Host "Using claude: $claudeCmd"

# Capture EVERYTHING shown in the terminal to a log file (for morning review).
# This does NOT break the interactive UI -- transcript runs in parallel.
try { Start-Transcript -Path $transcript -Append | Out-Null } catch {}

Write-Host ""
Write-Host "================================================================"
Write-Host "  coop-hunter -- overnight runner (interactive mode)"
Write-Host "================================================================"
Write-Host "  Started:       $(Get-Date)"
Write-Host "  Repo:          $repoRoot"
Write-Host "  Transcript:    $transcript"
Write-Host ""
Write-Host "  You will see the chat live in THIS window."
Write-Host "  All permissions are auto-approved (--dangerously-skip-permissions)."
Write-Host "  The /goal prompt is sent as the first message automatically."
Write-Host "  If claude exits early, this script restarts it (up to 20 times)."
Write-Host ""
Write-Host "  To stop: Ctrl+C in this window."
Write-Host "================================================================"
Write-Host ""

# The single prompt that does everything. /goal makes Claude loop across turns
# until the completion condition is met.
$goalPrompt = @'
/goal Run the coop-hunter skill from .claude/skills/coop-hunter/ to expand data.js with new PC co-op games.

Strict rules (read SKILL.md and classification.md before starting):

1. Process candidates sequentially from sources.json in the order defined. Sleep 1.5s between Steam API calls. Process ONLY 3-5 candidates per turn before returning control.

2. Persist progress to state/progress.json AFTER EVERY game added or skipped. Append to state/added.tsv and state/skipped.tsv. This is non-negotiable - if you skip persistence and crash, work is lost.

3. Run a validation pass (spawn a fresh general-purpose Agent) every 50 added games. Log failures to state/validation-fails.tsv. Do NOT auto-correct - only log.

4. NEVER ASK QUESTIONS. For every decision, use the deterministic rules in classification.md. If a candidate is genuinely ambiguous, append to state/skipped.tsv with reason "ambiguous" and continue. The user is asleep - there is nobody to answer.

5. If a tool call fails, retry once with 5s extra sleep. On second failure, log to skipped and continue. Do NOT halt for transient errors.

6. Do NOT modify app.js, index.html, or styles.css. ONLY modify data.js (via scripts/append_entry.py, never by hand-editing).

7. Do NOT create new files outside .claude/skills/coop-hunter/state/ and data.js. Do NOT touch git (no commits during the run - user will review in the morning).

Continue until ANY of:
(a) all 9 sources are marked completed in progress.json,
(b) progress.json shows done=true,
(c) you have added 300 new games this session.

Output a single line summary every 10 additions: "[N added] [skip: K] [src: source_id] [last: <title>]"

The user is offline overnight. Make autonomous, conservative, rule-based decisions. When in doubt, SKIP rather than add - quality beats volume.
'@

$initialAdded = 0
if (Test-Path $progressFile) {
  $p = Get-Content $progressFile -Raw | ConvertFrom-Json
  $initialAdded = $p.added_count
}
Write-Host "Starting added_count (from progress.json): $initialAdded"
Write-Host ""

$maxRestarts = 20
$run = 0

while ($true) {
  $run++
  Write-Host ""
  Write-Host "[$(Get-Date)] ============ Run #$run ============" -ForegroundColor Yellow
  Write-Host ""

  # Interactive mode -- positional arg sends the prompt as the first message.
  # No -p flag = stays interactive after the prompt, you see the chat live.
  # Loop exits naturally when claude exits (user quits, /goal completes, or crash).
  & $claudeCmd --dangerously-skip-permissions $goalPrompt

  # After claude exits, check progress.
  if (-not (Test-Path $progressFile)) {
    Write-Host ""
    Write-Host "[$(Get-Date)] WARNING: progress.json not found. Stopping." -ForegroundColor Red
    break
  }

  $progress = Get-Content $progressFile -Raw | ConvertFrom-Json
  Write-Host ""
  Write-Host "[$(Get-Date)] Claude exited. progress: added=$($progress.added_count) skipped=$($progress.skipped_count) done=$($progress.done)" -ForegroundColor Cyan

  if ($progress.done) {
    Write-Host ""
    Write-Host "[$(Get-Date)] SKILL MARKED DONE. Stopping." -ForegroundColor Green
    break
  }

  if ($run -ge $maxRestarts) {
    Write-Host ""
    Write-Host "[$(Get-Date)] Reached max restart limit ($maxRestarts). Stopping." -ForegroundColor Red
    break
  }

  Write-Host ""
  Write-Host "[$(Get-Date)] Skill not done -- restarting claude in 30 seconds. Ctrl+C to stop." -ForegroundColor Yellow
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
  Write-Host "  Total added (file):   $($final.added_count)"
  Write-Host "  Skipped total:        $($final.skipped_count)"
  Write-Host "  Sources completed:    $($final.completed_sources -join ', ')"
}
Write-Host ""
Write-Host "Review:"
Write-Host "  Transcript:     $transcript"
Write-Host "  Added:          $repoRoot\.claude\skills\coop-hunter\state\added.tsv"
Write-Host "  Skipped:        $repoRoot\.claude\skills\coop-hunter\state\skipped.tsv"
Write-Host "  Validation:     $repoRoot\.claude\skills\coop-hunter\state\validation-fails.tsv"
Write-Host ""
Write-Host "After review: git diff data.js && git add data.js && git commit && git push"

try { Stop-Transcript | Out-Null } catch {}
