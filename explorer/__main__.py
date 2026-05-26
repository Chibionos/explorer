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
from .runner.interview import run_interactive_claude
from .tui.app import ExplorerApp
from .tui.plan_screen import PlanScreen

import yaml


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

    # ---- Planner interview ----
    answers: asyncio.Queue[str] = asyncio.Queue()

    async def watch_for_plan():
        async for ev in bus.subscribe("plan_ready"):
            scenarios = ev.data.get("scenarios", [])
            run_paths.plan_yaml.write_text(
                yaml.safe_dump({"scenarios": scenarios}, sort_keys=False))
            for s in scenarios:
                queue.propose(Scenario(id=s["id"], title=s["title"], goal=s["goal"]))
            return scenarios

    plan_watcher = asyncio.create_task(watch_for_plan())

    prompt_planner = (Path(__file__).parent / "runner/prompts/system_planner.md").read_text()
    env = {"EXPLORER_EVENT_LOG": str(run_paths.event_log_for_subprocess)}
    planner_task = asyncio.create_task(run_interactive_claude(
        prompt=prompt_planner, cwd=Path(cfg.codebase_path),
        env_overrides=env, bus=bus, session_label="planner", answers=answers,
    ))

    # ---- TUI ----
    plan_screen = PlanScreen(answers=answers)

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
    for t in (tailer, persist_task, plan_watcher, planner_task,
              bug_handler, proposed_handler):
        t.cancel()
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
