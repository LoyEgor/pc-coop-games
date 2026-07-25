#!/usr/bin/env python3
"""
Watchdog for the data-refresh automation. Run daily by .github/workflows/health-check.yml,
about an hour after the refresh window.

Every past outage of this automation was silent and found weeks late (history in
CLAUDE.md §8a). This script is the missing layer: it turns breakage into a GitHub issue
assigned to the repo owner — which emails him — plus a red run, within a day.

It checks independent things — the point is that they fail in different ways:
  1. heartbeat freshness  — `last_success` in .github/refresh-status.json. A broken
     commit/push step also lands here: the status file only reaches the repo via that
     step, so a stale checked-out heartbeat means green-but-not-committing.
  2. last outcome         — `last_failure` newer than `last_success` (crash class).
  3. sweep completion     — `sweep.last_full_cycle_at` (or cycle_started_at before the
     first close): the sweep is budgeted and resumable, so a run can be green every night
     while the tail of the catalog never gets visited.
  3b. sweep COVERAGE      — `sweep.last_cycle_unverified`: a cycle can also close having
     walked every entry while verifying few of them, when Steam refused the requests.
  3c. writer health       — `write_failures`: drift computed but never written to data.js.
  4. schedule liveness    — the newest refresh run's age + conclusion, and the workflow's
     own state. GitHub disables scheduled workflows in a public repo after 60 days
     without repository activity (bot pushes made with GITHUB_TOKEN do not count), so
     "no runs at all" is a real failure mode. A disabled workflow is re-enabled here.

Stdlib + the `gh` CLI (preinstalled on GitHub runners). Exit 0 healthy, 1 unhealthy.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_FILE = REPO_ROOT / ".github" / "refresh-status.json"
DRY_RUN = False  # --dry-run: report the verdict, touch no issues (used to test the watchdog itself)
WORKFLOW = "refresh-prices.yml"
LABEL = "cron-health"
ISSUE_TITLE = "⚠️ Data refresh automation is unhealthy"

HEARTBEAT_MAX_AGE_H = 30         # daily cron + slack for GitHub's schedule drift
RUN_MAX_AGE_H = 30               # a schedule that stopped firing at all
CYCLE_FALLBACK_TARGET_H = 96     # used when the status file carries no target
CYCLE_UNVERIFIED_MAX_REL = 0.15  # a closed cycle may leave at most this share unverified
WRITE_FAILURES_MAX = 3           # update_field.py refusals tolerated in one run


def gh(*args, check=True, mutates=False):
    """Run gh; return stdout. Never raises for `check=False` callers. `mutates=True`
    marks a call that changes something on GitHub — suppressed under --dry-run."""
    if mutates and DRY_RUN:
        print(f"  (dry-run) would run: gh {' '.join(args[:3])} …")
        return ""
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        if check:
            print(f"::warning::gh {' '.join(args)} failed: {r.stderr.strip()}", file=sys.stderr)
        return ""
    return r.stdout.strip()


def hours_since(ts):
    """Age in hours of an ISO-8601 timestamp (Z or offset form). None if unparseable."""
    if not ts:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    delta = datetime.datetime.now(datetime.timezone.utc) - parsed
    return delta.total_seconds() / 3600.0


def collect_problems():
    """List of (code, human-readable line). Empty list == healthy."""
    problems = []

    try:
        status = json.loads(STATUS_FILE.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return [("status_unreadable", f"`.github/refresh-status.json` is missing or unparseable ({e}).")]
    # Valid JSON is not enough: a list or a bare string would sail through json.loads and
    # then AttributeError on the first .get() — the watchdog would go red without ever
    # reaching the issue flow, i.e. fail silently in the one place that must not.
    if not isinstance(status, dict):
        return [("status_malformed", f"`.github/refresh-status.json` parsed as {type(status).__name__}, not an object.")]

    last_success, last_failure = status.get("last_success"), status.get("last_failure")

    age = hours_since(last_success)
    if age is None:
        problems.append(("no_heartbeat", "The status file carries no usable `last_success` timestamp."))
    elif age > HEARTBEAT_MAX_AGE_H:
        problems.append((
            "heartbeat_stale",
            f"Last successful refresh was **{age:.0f}h ago** (`{last_success}`), over the {HEARTBEAT_MAX_AGE_H}h window. "
            "Either the cron is not running, or it runs but no longer commits — the status file reaches the repo "
            "only through the commit step.",
        ))

    fail_age = hours_since(last_failure)
    if fail_age is not None and age is not None and fail_age < age:
        problems.append((
            "last_run_failed",
            f"The most recent run FAILED ({fail_age:.0f}h ago): `{status.get('last_failure_error', 'unknown')}`.",
        ))

    writes = status.get("write_failures")
    if isinstance(writes, int) and writes >= WRITE_FAILURES_MAX:
        problems.append((
            "writer_failing",
            f"The last run hit **{writes}** update_field.py refusals — verified drift is being computed but not "
            "written into data.js, so the catalog silently stops tracking Steam.",
        ))

    sweep = status.get("sweep") or {}
    cycle_at = sweep.get("last_full_cycle_at")
    target = sweep.get("full_cycle_target_hours") or CYCLE_FALLBACK_TARGET_H
    # Fall back to cycle_started_at: before the first cycle ever closes there is no
    # last_full_cycle_at, so keying only off that leaves the one check meant to catch
    # "green every night, catalog never actually swept" inert exactly when the sweep is
    # new — or after any reset of the cursor.
    cycle_ref = cycle_at or sweep.get("cycle_started_at")
    cycle_age = hours_since(cycle_ref)
    if sweep and cycle_ref and cycle_age is not None and cycle_age > target:
        what = ("has not completed a full pass over the catalog" if cycle_at
                else "has not finished its FIRST full pass since the cursor was reset")
        problems.append((
            "cycle_stalled",
            f"The sweep {what} in **{cycle_age:.0f}h** (target {target}h) — "
            f"currently at {sweep.get('cycle_visited', '?')}/{sweep.get('cycle_size', '?')} entries. "
            "Green runs alone do not mean every entry is being refreshed; raise `--budget-minutes` or shorten the cron interval.",
        ))

    # Coverage, not just progress: the cursor advances past entries Steam refused to
    # answer for, so a cycle can close having verified far less than it walked.
    size = sweep.get("cycle_size") or 0
    missed = sweep.get("last_cycle_unverified")
    if size and isinstance(missed, int) and missed > size * CYCLE_UNVERIFIED_MAX_REL:
        problems.append((
            "cycle_coverage_thin",
            f"The last completed cycle left **{missed}/{size}** entries unverified "
            f"({missed / size:.0%}, limit {CYCLE_UNVERIFIED_MAX_REL:.0%}) — Steam refused a large share of requests, "
            "so those prices and ratings are older than the cycle stamp suggests.",
        ))

    runs = gh("run", "list", "--workflow", WORKFLOW, "--limit", "1",
              "--json", "createdAt,conclusion,status,url", check=False)
    try:
        newest = (json.loads(runs) or [None])[0] if runs else None
    except json.JSONDecodeError:
        newest = None

    if newest is None:
        problems.append(("no_runs_visible", f"Could not read any recent run of `{WORKFLOW}` from the Actions API."))
    else:
        run_age = hours_since(newest.get("createdAt"))
        if run_age is not None and run_age > RUN_MAX_AGE_H:
            problems.append((
                "schedule_not_firing",
                f"The newest `{WORKFLOW}` run started **{run_age:.0f}h ago**. The schedule appears to have stopped firing "
                "(GitHub disables cron workflows in a public repo after 60 days without repository activity).",
            ))
        if newest.get("status") == "completed" and newest.get("conclusion") not in (None, "success"):
            problems.append((
                "run_not_successful",
                f"The newest run ended as **{newest.get('conclusion')}**: {newest.get('url', '')}",
            ))

    state = gh("api", f"repos/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/workflows/{WORKFLOW}",
               "--jq", ".state", check=False)
    if state and state != "active":
        problems.append((
            "workflow_disabled",
            f"The `{WORKFLOW}` workflow is **{state}** — re-enabling it automatically now. "
            "If this keeps happening, add a `KEEPALIVE_TOKEN` secret so the weekly keepalive commit "
            "can reset GitHub's 60-day inactivity timer.",
        ))
        gh("api", "-X", "PUT",
           f"repos/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/workflows/{WORKFLOW}/enable", check=False, mutates=True)

    return problems


def issue_body(problems, status_text):
    codes = ",".join(code for code, _ in problems)
    lines = [
        f"<!-- health-check codes: {codes} -->",
        "The daily data-refresh automation is not healthy. This issue is opened, updated and "
        "closed automatically by `.github/workflows/health-check.yml`.",
        "",
        "### What is wrong",
    ]
    lines += [f"- {text}" for _, text in problems]
    lines += [
        "",
        "### Where to look",
        f"- Actions run history: [`{WORKFLOW}`](../actions/workflows/{WORKFLOW})",
        "- Heartbeat: [`.github/refresh-status.json`](../blob/main/.github/refresh-status.json)",
        "- Sweep model and thresholds: header comment of `.github/scripts/refresh.py`",
        "",
        "<details><summary>Current heartbeat</summary>",
        "",
        "```json",
        status_text.strip(),
        "```",
        "",
        "</details>",
        "",
        f"_Checked {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC._",
    ]
    return "\n".join(lines)


def open_health_issue():
    """(number, body, ok) for the open cron-health issue. `ok` is False when the LOOKUP
    failed: a successful `gh issue list` prints "[]" for no results, so an empty string
    means the call itself broke. Reading that as "no issue exists" would open a fresh
    duplicate on every transient API/auth error and the codes_marker dedup would never
    catch up."""
    raw = gh("issue", "list", "--label", LABEL, "--state", "open", "--limit", "1",
             "--json", "number,body")
    if not raw:
        return None, "", False
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return None, "", False
    if not items:
        return None, "", True
    return items[0].get("number"), items[0].get("body") or "", True


def main():
    global DRY_RUN, STATUS_FILE
    p = argparse.ArgumentParser(description="Watchdog over the data-refresh cron")
    p.add_argument("--dry-run", action="store_true", help="print the verdict; create/close no issues")
    p.add_argument("--status", help="read a different heartbeat file (for testing the alarm itself)")
    args = p.parse_args()
    DRY_RUN = args.dry_run
    if args.status:
        STATUS_FILE = Path(args.status)

    problems = collect_problems()
    status_text = STATUS_FILE.read_text() if STATUS_FILE.exists() else "(status file missing)"
    number, existing_body, lookup_ok = open_health_issue()

    if not problems:
        print("HEALTHY: refresh cron is fresh, last run succeeded, sweep is completing cycles.")
        if number:
            gh("issue", "comment", str(number), "--body",
               "✅ Recovered — the refresh automation is healthy again. Closing automatically.", check=False, mutates=True)
            gh("issue", "close", str(number), check=False, mutates=True)
            print(f"Closed recovered health issue #{number}.")
        return 0

    for code, text in problems:
        print(f"::error::[{code}] {text}")

    body = issue_body(problems, status_text)
    codes_marker = body.splitlines()[0]
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")

    if number:
        gh("issue", "edit", str(number), "--body", body, check=False, mutates=True)
        # Comment only when the diagnosis actually changed — a daily "still broken"
        # comment would train the owner to ignore the notification.
        if codes_marker not in existing_body:
            gh("issue", "comment", str(number), "--body",
               "The diagnosis changed:\n\n" + "\n".join(f"- {t}" for _, t in problems), check=False, mutates=True)
        print(f"Updated health issue #{number}.")
    elif not lookup_ok:
        print("::warning::could not read the existing health issues — reporting the problems in this log "
              "only, rather than risking a duplicate issue every day. The job still fails.")
    else:
        gh("label", "create", LABEL, "--color", "B60205",
           "--description", "Automated data-refresh health alerts", "--force", check=False, mutates=True)
        args = ["issue", "create", "--title", ISSUE_TITLE, "--body", body, "--label", LABEL]
        if owner:
            args += ["--assignee", owner]
        url = gh(*args, check=False, mutates=True)
        if DRY_RUN:
            print("Would open a new health issue (dry-run).")
        else:
            print(f"Opened health issue: {url or '(creation failed — see warnings above)'}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
