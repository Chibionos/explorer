from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

from .config.cli import parse_args, resolve_config
from .config.project_yaml import save as save_project_yaml
from .core.event_bus import EventBus, Event
from .core.scenario_queue import ScenarioQueue, Scenario
from .core.bug_store import BugStore, Bug
from .core.dedup import DedupIndex
from .core.browser_lock import BrowserLock
from .core.run_paths import RunPaths
from .runner.event_log_tailer import tail_event_log
from .runner.explorer import run_explorer
from .runner.planner import run_planner_with_answers
from .runner.tabs import list_chrome_tabs
from .runner.confluence import run_confluence_setup, run_confluence_writer
from .tui.app import ExplorerApp
from .tui.plan_screen import PlanScreen
from .tui.tab_picker import TabPickerScreen
from .cli.status import cmd_status
from .cli.tail import cmd_tail
from dataclasses import replace as _replace

import yaml


def _load_plan_file(path: Path) -> list[Scenario]:
    data = yaml.safe_load(path.read_text())
    return [Scenario(id=s["id"], title=s["title"], goal=s["goal"])
            for s in data.get("scenarios", [])]


def _scenarios_to_yaml(scenarios: list[Scenario]) -> str:
    return yaml.safe_dump(
        {"scenarios": [{"id": s.id, "title": s.title, "goal": s.goal}
                       for s in scenarios]},
        sort_keys=False,
    )


def _replay_completed_scenarios(events_log: Path) -> set[str]:
    """Read events.jsonl and return ids of scenarios that emitted scenario_done."""
    done: set[str] = set()
    if not events_log.exists():
        return done
    for line in events_log.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "scenario_done":
            sid = (ev.get("data") or {}).get("scenario_id")
            if sid:
                done.add(sid)
    return done


def _resolve_resume_path(resume_arg: str, base: Path) -> Path:
    """Turn --resume's argument into an absolute run dir."""
    if resume_arg == "latest":
        rp = RunPaths.latest(base)
        if rp is None:
            raise FileNotFoundError(
                f"--resume latest: no prior runs under {base / 'runs'}")
        return rp.root
    p = Path(resume_arg)
    if not p.is_absolute():
        # Allow relative paths like ".explorer/runs/<ts>" or "<ts>"
        if (base / "runs" / resume_arg).exists():
            p = base / "runs" / resume_arg
        else:
            p = Path.cwd() / resume_arg
    if not p.exists():
        raise FileNotFoundError(f"--resume: run dir not found: {p}")
    return p


async def amain() -> int:
    args = parse_args(sys.argv[1:])
    project_dir = Path.cwd()
    cfg = resolve_config(args, project_dir=project_dir)

    # --resume + --plan conflict; prefer explicit error over silent priority.
    if args.resume and args.plan:
        print("--resume and --plan can't be used together: resume reuses the "
              "plan from the prior run dir.", file=sys.stderr)
        return 2

    if args.resume:
        try:
            resume_root = _resolve_resume_path(args.resume, project_dir / ".explorer")
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 2
        run_paths = RunPaths.existing(resume_root)
    else:
        run_paths = RunPaths.new(base=project_dir / ".explorer")

    bus = EventBus()
    queue = ScenarioQueue.from_scenarios([])
    # BugStore auto-loads existing bugs.json if the file exists.
    bugs = BugStore(mirror_path=run_paths.bugs_json)
    dedup = DedupIndex.from_pairs([(b.title, b.jira_key) for b in bugs.all()])
    lock = BrowserLock()

    tailer = asyncio.create_task(tail_event_log(run_paths.event_log_for_subprocess, bus))

    async def persist_events():
        async for ev in bus.subscribe("*"):
            with run_paths.events_log.open("a") as f:
                f.write(json.dumps({"type": ev.type, "data": ev.data}) + "\n")
    persist_task = asyncio.create_task(persist_events())

    # ---- Plan source: --plan file vs. interactive interview ----
    answers_out: asyncio.Queue[list[str]] = asyncio.Queue()
    plan_screen = PlanScreen(answers_out=answers_out)
    planner_task: asyncio.Task | None = None

    if args.resume:
        # Reuse the prior run's plan.yaml. Mark already-completed scenarios DONE.
        if not run_paths.plan_yaml.exists():
            print(f"--resume: prior run has no plan.yaml at {run_paths.plan_yaml}",
                  file=sys.stderr)
            return 2
        scenarios = _load_plan_file(run_paths.plan_yaml)
        for s in scenarios:
            queue.propose(s)
        completed_already = _replay_completed_scenarios(run_paths.events_log)
        for sid in completed_already:
            if sid in {s.id for s in queue.scenarios()}:
                queue.mark_done(sid)
        # Auto-approve: nothing to review, we're picking up where we stopped.
        plan_screen.set_auto_approve(_scenarios_to_yaml(scenarios))
    elif args.plan:
        # Pre-made plan from a YAML file. Skip planner + interview entirely.
        plan_path = Path(args.plan)
        if not plan_path.exists():
            print(f"--plan: file not found: {plan_path}", file=sys.stderr)
            return 2
        scenarios = _load_plan_file(plan_path)
        for s in scenarios:
            queue.propose(s)
        run_paths.plan_yaml.write_text(plan_path.read_text())

        if args.yes:
            plan_screen.set_auto_approve(_scenarios_to_yaml(scenarios))
        else:
            plan_screen.set_preloaded_plan(_scenarios_to_yaml(scenarios))
    else:
        # Interactive: TUI walks through questions, then planner subprocess
        # converts answers into a plan_ready event.
        async def run_planner_after_answers():
            answers = await answers_out.get()
            return await run_planner_with_answers(
                answers=answers,
                event_log=run_paths.event_log_for_subprocess,
                bus=bus,
                codebase_path=Path(cfg.codebase_path),
            )
        planner_task = asyncio.create_task(run_planner_after_answers())

        async def watch_for_plan():
            async for ev in bus.subscribe("plan_ready"):
                scenarios = ev.data.get("scenarios", [])
                run_paths.plan_yaml.write_text(
                    yaml.safe_dump({"scenarios": scenarios}, sort_keys=False))
                for s in scenarios:
                    queue.propose(Scenario(id=s["id"], title=s["title"], goal=s["goal"]))
                return scenarios
        plan_watcher = asyncio.create_task(watch_for_plan())

    # Track which scenarios actually emitted scenario_done — a clean exit
    # without scenario_done means the explorer bailed (e.g. wrong page),
    # which should NOT count as "done".
    completed_scenarios: set[str] = set()

    async def watch_scenario_done():
        async for ev in bus.subscribe("scenario_done"):
            sid = ev.data.get("scenario_id")
            if sid:
                completed_scenarios.add(sid)
    scenario_done_watcher = asyncio.create_task(watch_scenario_done())

    # Snapshot of original plan, used by --continuous to requeue rounds.
    original_scenarios = list(queue.scenarios())

    async def runner():
        scen_idx = 0
        round_n = 1
        while True:
            if queue.all_done():
                if not args.continuous:
                    break
                # --continuous: start a new round by requeuing the original plan
                # with bumped ids (so dedup-by-id doesn't drop them).
                round_n += 1
                for s in original_scenarios:
                    queue.propose(Scenario(
                        id=f"{s.id}-r{round_n}",
                        title=f"[round {round_n}] {s.title}",
                        goal=s.goal,
                    ))
                await asyncio.sleep(0.1)
                continue
            scen = queue.next_pending()
            if scen is None:
                await asyncio.sleep(0.5)
                continue
            queue.mark_running(scen.id)
            scen_idx += 1
            async with lock.acquire():
                rc = await run_explorer(
                    scenario=scen, codebase_path=Path(cfg.codebase_path),
                    event_log=run_paths.event_log_for_subprocess,
                    screenshots_dir=run_paths.screenshots_dir,
                    jira_project=cfg.jira_project, epic_key=cfg.epic_key,
                    dedup=dedup, bus=bus, session_label=f"explorer-{scen_idx}",
                    tab_url=app.current_tab_url(),
                    bu_name=cfg.bu_name,
                )
            # Give the tailer a tick to flush pending scenario_done events.
            await asyncio.sleep(0.2)
            if rc != 0:
                queue.mark_failed(scen.id, f"exit {rc}")
            elif scen.id in completed_scenarios:
                queue.mark_done(scen.id)
            else:
                queue.mark_failed(scen.id, "explorer exited without scenario_done (likely aborted)")

    async def handle_bug_filed():
        async for ev in bus.subscribe("bug_filed"):
            d = ev.data
            bugs.add(Bug(uuid=d["uuid"], jira_key=d["jira_key"], title=d["title"],
                        scenario_id=d.get("scenario_id", ""),
                        screenshot_path=d.get("screenshot_path", ""),
                        jira_url=d.get("jira_url", "")))
            dedup.record(d["title"], d["jira_key"])

    async def handle_proposed():
        async for ev in bus.subscribe("scenario_proposed"):
            d = ev.data
            queue.propose(Scenario(id=d["id"], title=d["title"], goal=d["goal"],
                                   parent_id=d.get("parent_scenario_id")))

    bug_handler = asyncio.create_task(handle_bug_filed())
    proposed_handler = asyncio.create_task(handle_proposed())

    # ---- Confluence integration (optional) ----
    # Track screenshots + bugs per scenario so we can hand them to the
    # confluence-writer agent on scenario_done.
    confluence_page_id: str | None = cfg.confluence_page
    scenario_screenshots: dict[str, list[Path]] = {}
    scenario_bugs: dict[str, list[tuple[str, str]]] = {}
    current_scenario_id: str | None = None

    async def watch_confluence_page_ready():
        nonlocal confluence_page_id
        async for ev in bus.subscribe("confluence_page_ready"):
            new_id = ev.data.get("page_id")
            if new_id:
                confluence_page_id = new_id
                # Persist so future runs from this cwd default to the same page.
                nonlocal_cfg = _replace(cfg, confluence_page=new_id)
                save_project_yaml(nonlocal_cfg, project_dir / ".explorer" / "project.yaml")
            return
    confluence_ready_watcher = asyncio.create_task(watch_confluence_page_ready())

    async def watch_scenario_screenshots_and_bugs():
        nonlocal current_scenario_id
        async for ev in bus.subscribe("*"):
            d = ev.data or {}
            if ev.type == "scenario_start":
                current_scenario_id = d.get("scenario_id")
                if current_scenario_id:
                    scenario_screenshots.setdefault(current_scenario_id, [])
                    scenario_bugs.setdefault(current_scenario_id, [])
            elif ev.type == "bug_observed":
                sid = d.get("scenario_id") or current_scenario_id
                shot = d.get("screenshot_path")
                if sid and shot:
                    scenario_screenshots.setdefault(sid, []).append(Path(shot))
            elif ev.type == "bug_filed":
                sid = d.get("scenario_id") or current_scenario_id
                key, title = d.get("jira_key", ""), d.get("title", "")
                if sid and key:
                    scenario_bugs.setdefault(sid, []).append((key, title))
    scen_evidence_watcher = asyncio.create_task(watch_scenario_screenshots_and_bugs())

    async def watch_scenario_done_for_confluence():
        async for ev in bus.subscribe("scenario_done"):
            if not confluence_page_id:
                continue
            sid = ev.data.get("scenario_id")
            if not sid:
                continue
            # Look up the scenario record for its title + goal.
            scen = next((s for s in queue.scenarios() if s.id == sid), None)
            title = scen.title if scen else sid
            goal = scen.goal if scen else ""
            await run_confluence_writer(
                page_id=confluence_page_id,
                scenario_id=sid,
                scenario_title=title,
                scenario_goal=goal,
                scenario_status="done",
                bugs_filed=scenario_bugs.get(sid, []),
                screenshot_paths=scenario_screenshots.get(sid, []),
                run_dir=run_paths.root,
                tab_url=app.current_tab_url() if 'app' in locals() else cfg.tab_url,
                codebase_path=Path(cfg.codebase_path),
                event_log=run_paths.event_log_for_subprocess,
                bus=bus,
            )
    confluence_writer_task = asyncio.create_task(watch_scenario_done_for_confluence())

    # Kick off confluence setup if requested.
    if cfg.confluence_page:
        asyncio.create_task(run_confluence_setup(
            mode="use", space=None, page_id=cfg.confluence_page,
            run_label=run_paths.root.name,
            codebase_path=Path(cfg.codebase_path),
            event_log=run_paths.event_log_for_subprocess, bus=bus,
        ))
    elif cfg.confluence_space:
        asyncio.create_task(run_confluence_setup(
            mode="create", space=cfg.confluence_space, page_id=None,
            run_label=run_paths.root.name,
            codebase_path=Path(cfg.codebase_path),
            event_log=run_paths.event_log_for_subprocess, bus=bus,
        ))

    # When the user picks/changes the tab in the TUI, persist it so the next
    # run from this cwd picks the same tab by default.
    project_yaml_path = project_dir / ".explorer" / "project.yaml"

    def _on_tab_changed(new_url: str) -> None:
        nonlocal cfg
        cfg = _replace(cfg, tab_url=new_url)
        save_project_yaml(cfg, project_yaml_path)

    app = ExplorerApp(
        cfg=cfg, bus=bus, queue=queue, bugs=bugs, run_paths=run_paths,
        plan_screen=plan_screen, scenario_runner=runner,
        force_tab_picker=args.pick_tab,
        on_tab_changed=_on_tab_changed,
    )
    await app.run_async()

    # shutdown
    tasks_to_cancel = [tailer, persist_task, bug_handler, proposed_handler,
                       scenario_done_watcher, confluence_ready_watcher,
                       scen_evidence_watcher, confluence_writer_task]
    if planner_task is not None:
        tasks_to_cancel.append(planner_task)
    if 'plan_watcher' in locals():
        tasks_to_cancel.append(plan_watcher)
    for t in tasks_to_cancel:
        t.cancel()
    return 0


def main() -> None:
    # Subcommand routing. `explorer status` and `explorer tail` are non-TUI
    # helpers for coding agents to inspect a running session from outside.
    # No subcommand (or `explorer run …`) → launch the TUI.
    if len(sys.argv) >= 2 and sys.argv[1] in ("status", "tail"):
        cmd = sys.argv.pop(1)
        if cmd == "status":
            sys.exit(cmd_status(sys.argv[1:]))
        if cmd == "tail":
            sys.exit(cmd_tail(sys.argv[1:]))
    if len(sys.argv) >= 2 and sys.argv[1] == "run":
        sys.argv.pop(1)
    sys.exit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
