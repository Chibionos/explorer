from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

from .config.cli import parse_args, resolve_config
from .core.event_bus import EventBus, Event
from .core.scenario_queue import ScenarioQueue, Scenario
from .core.bug_store import BugStore, Bug
from .core.dedup import DedupIndex
from .core.browser_lock import BrowserLock
from .core.run_paths import RunPaths
from .runner.event_log_tailer import tail_event_log
from .runner.explorer import run_explorer
from .runner.planner import run_planner_with_answers
from .tui.app import ExplorerApp
from .tui.plan_screen import PlanScreen

import yaml


def _load_plan_file(path: Path) -> list[Scenario]:
    data = yaml.safe_load(path.read_text())
    return [Scenario(id=s["id"], title=s["title"], goal=s["goal"])
            for s in data.get("scenarios", [])]


async def amain() -> int:
    args = parse_args(sys.argv[1:])
    project_dir = Path.cwd()
    cfg = resolve_config(args, project_dir=project_dir)

    run_paths = RunPaths.new(base=project_dir / ".explorer")
    bus = EventBus()
    queue = ScenarioQueue.from_scenarios([])
    bugs = BugStore(mirror_path=run_paths.bugs_json)
    dedup = DedupIndex.from_pairs([])
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

    if args.plan:
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
            # Auto-approve: emit a fake "approved" dismiss on first paint by
            # having the screen put a plan_ready into the bus and skipping
            # right past approval.
            plan_screen.set_auto_approve(yaml.safe_dump(
                {"scenarios": [{"id": s.id, "title": s.title, "goal": s.goal}
                               for s in scenarios]}, sort_keys=False))
        else:
            # Show the plan in the approval screen so user can sanity-check.
            plan_screen.set_preloaded_plan(yaml.safe_dump(
                {"scenarios": [{"id": s.id, "title": s.title, "goal": s.goal}
                               for s in scenarios]}, sort_keys=False))
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

    async def runner():
        scen_idx = 0
        while not queue.all_done():
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
                    bu_name=cfg.bu_name,
                )
            if rc == 0:
                queue.mark_done(scen.id)
            else:
                queue.mark_failed(scen.id, f"exit {rc}")

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

    app = ExplorerApp(
        cfg=cfg, bus=bus, queue=queue, bugs=bugs, run_paths=run_paths,
        plan_screen=plan_screen, scenario_runner=runner,
    )
    await app.run_async()

    # shutdown
    tasks_to_cancel = [tailer, persist_task, bug_handler, proposed_handler]
    if planner_task is not None:
        tasks_to_cancel.append(planner_task)
    if 'plan_watcher' in locals():
        tasks_to_cancel.append(plan_watcher)
    for t in tasks_to_cancel:
        t.cancel()
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
