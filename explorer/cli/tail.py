"""`explorer tail` — stream events.jsonl with friendly formatting."""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

from ..core.run_paths import RunPaths


_PRIORITY = {"bug_filed": "→ BUG ", "scenario_start": "▶ START", "scenario_done": "✓ DONE",
             "bug_observed": "‼ OBS ", "scenario_proposed": "+ NEW ",
             "process_start": "● PROC", "process_exit": "○ EXIT",
             "confluence_updated": "📋 CONF", "subagent_start": "→ SUB ",
             "subagent_end": "  ← SUB"}


def _fmt(ev: dict) -> str:
    etype = ev.get("type", "?")
    data = ev.get("data", {})
    tag = _PRIORITY.get(etype, f"  {etype[:5]:5}")
    label = data.get("session_label", "")
    if etype == "note":
        return f"  note   {label[:14]:14} {data.get('text','')[:160]}"
    if etype == "bug_filed":
        return f"{tag}   {data.get('jira_key','')} {data.get('title','')[:120]}"
    if etype == "bug_observed":
        return f"{tag}   {data.get('title','')[:140]}"
    if etype == "scenario_start" or etype == "scenario_done":
        return f"{tag}   {data.get('scenario_id','')}: {data.get('title','')[:100]}"
    if etype in ("process_start", "process_exit"):
        rest = f"pid {data.get('pid','')}" if etype == "process_start" else f"rc {data.get('returncode','')}"
        return f"{tag}   {label[:14]:14} {rest}"
    if etype == "subagent_start":
        return f"{tag}   {label[:14]:14} {data.get('description','')[:120]}"
    return f"{tag}   {json.dumps(data)[:160]}"


def cmd_tail(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="explorer tail",
        description="Stream the events log of the current/latest run with friendly formatting.",
    )
    p.add_argument("--run-dir",
                   help="Explicit run directory (default: latest under cwd/.explorer/runs).")
    p.add_argument("--from-start", action="store_true",
                   help="Print all events from the beginning (default: only new ones).")
    p.add_argument("--filter",
                   help="Only show events whose type matches this substring "
                        "(e.g. --filter bug_filed).")
    args = p.parse_args(argv)

    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        rp = RunPaths.latest(Path.cwd() / ".explorer")
        if rp is None:
            print("no runs under ./.explorer/runs", file=sys.stderr)
            return 2
        run_dir = rp.root

    log = run_dir / "events.jsonl"
    print(f"# tailing {log}", file=sys.stderr)
    log.touch()
    pos = 0 if args.from_start else log.stat().st_size

    try:
        while True:
            with log.open() as f:
                f.seek(pos)
                for line in f:
                    if not line.endswith("\n"):
                        break
                    pos += len(line.encode())
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if args.filter and args.filter not in ev.get("type", ""):
                        continue
                    print(_fmt(ev), flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
