"""`explorer status` — non-TUI summary of the current/latest run.

Designed for coding agents (and humans) to check progress from outside the TUI.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from ..core.run_paths import RunPaths


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _parse_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def cmd_status(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="explorer status",
        description="One-shot summary of the current or latest explorer run.",
    )
    p.add_argument("--run-dir",
                   help="Explicit run directory (default: latest under cwd/.explorer/runs).")
    p.add_argument("--json", action="store_true",
                   help="Machine-readable JSON output for coding agents.")
    p.add_argument("--last", type=int, default=5,
                   help="How many recent events to include (default 5).")
    args = p.parse_args(argv)

    if args.run_dir:
        run_dir = Path(args.run_dir)
        if not run_dir.exists():
            print(f"run dir not found: {run_dir}", file=sys.stderr)
            return 2
    else:
        rp = RunPaths.latest(Path.cwd() / ".explorer")
        if rp is None:
            print("no runs under ./.explorer/runs", file=sys.stderr)
            return 2
        run_dir = rp.root

    events = _parse_events(run_dir / "events.jsonl")

    # Bugs.
    bugs_path = run_dir / "bugs.json"
    bugs = json.loads(bugs_path.read_text()) if bugs_path.exists() else []

    # Process state.
    process_starts: dict[str, int] = {}     # session_label -> pid
    process_exits: set[str] = set()
    for ev in events:
        if ev.get("type") == "process_start":
            label = ev["data"].get("session_label", "?")
            process_starts[label] = ev["data"].get("pid", 0)
        elif ev.get("type") == "process_exit":
            process_exits.add(ev["data"].get("session_label", "?"))

    running: list[tuple[str, int]] = []
    for label, pid in process_starts.items():
        if label in process_exits:
            continue
        if pid and _is_process_alive(pid):
            running.append((label, pid))

    # Scenario progress.
    started_scenarios: set[str] = set()
    done_scenarios: set[str] = set()
    for ev in events:
        if ev.get("type") == "scenario_start":
            sid = ev["data"].get("scenario_id")
            if sid:
                started_scenarios.add(sid)
        elif ev.get("type") == "scenario_done":
            sid = ev["data"].get("scenario_id")
            if sid:
                done_scenarios.add(sid)

    # Event type counter.
    type_counts = Counter(ev.get("type", "?") for ev in events)

    recent = events[-args.last:] if args.last > 0 else []

    summary = {
        "run_dir": str(run_dir),
        "status": "running" if running else "idle",
        "running_processes": [{"label": l, "pid": pid} for l, pid in running],
        "bugs_filed": len(bugs),
        "bugs": [
            {"jira_key": b["jira_key"], "title": b["title"], "url": b.get("jira_url", "")}
            for b in bugs
        ],
        "scenarios_started": sorted(started_scenarios),
        "scenarios_done": sorted(done_scenarios),
        "scenarios_in_progress": sorted(started_scenarios - done_scenarios),
        "event_type_counts": dict(type_counts),
        "recent_events": recent,
    }

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
        return 0

    # Human-readable.
    print(f"Run: {run_dir}")
    print(f"Status: {summary['status']}")
    if running:
        for label, pid in running:
            print(f"  ⏵ {label}  (pid {pid})")
    print()
    print(f"Bugs filed: {len(bugs)}")
    for b in bugs:
        print(f"  {b['jira_key']:10}  {b['title']}")
    print()
    print(f"Scenarios: {len(done_scenarios)} done / {len(started_scenarios)} started")
    for sid in summary["scenarios_in_progress"]:
        print(f"  ⏵ {sid}")
    for sid in sorted(done_scenarios):
        print(f"  ✓ {sid}")
    print()
    if recent:
        print(f"Last {len(recent)} events:")
        for ev in recent:
            data = ev.get("data", {})
            etype = ev.get("type", "?")
            label = data.get("session_label", "")
            if etype == "note":
                print(f"  {label}: {data.get('text', '')[:120]}")
            elif etype == "bug_filed":
                print(f"  → bug filed: {data.get('jira_key')} {data.get('title','')}")
            else:
                short = json.dumps({k: v for k, v in data.items() if k != "text"})[:120]
                print(f"  [{etype}] {short}")
    return 0
