from __future__ import annotations
import asyncio
from typing import Awaitable, Callable
from textual.app import App, ComposeResult
from textual.containers import Horizontal

from ..core.event_bus import EventBus
from ..core.bug_store import BugStore
from ..core.scenario_queue import ScenarioQueue
from ..core.run_paths import RunPaths
from ..config.project_yaml import ProjectConfig
from .header import Header
from .log_strip import LogStrip
from .sessions_pane import SessionsPane
from .bugs_pane import BugsPane
from .plan_screen import PlanScreen


class ExplorerApp(App):
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        ("q", "quit", "quit"),
        ("e", "toggle_log", "expand log"),
    ]

    def __init__(
        self, *, cfg: ProjectConfig, bus: EventBus, queue: ScenarioQueue,
        bugs: BugStore, run_paths: RunPaths,
        plan_screen: PlanScreen,
        scenario_runner: Callable[[], Awaitable[None]],
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._bus = bus
        self._queue = queue
        self._bugs = bugs
        self._run_paths = run_paths
        self._plan_screen = plan_screen
        self._scenario_runner = scenario_runner

    def compose(self) -> ComposeResult:
        self.header = Header(id="header")
        self.header.jira_project = self._cfg.jira_project
        self.header.epic_key = self._cfg.epic_key
        self.header.codebase_path = self._cfg.codebase_path
        yield self.header
        self.sessions_pane = SessionsPane()
        self.sessions_pane.id = "sessions"
        self.bugs_pane = BugsPane(self._bugs)
        self.bugs_pane.id = "bugs"
        with Horizontal():
            yield self.sessions_pane
            yield self.bugs_pane
        self.log_strip = LogStrip()
        self.log_strip.id = "log"
        yield self.log_strip

    async def on_mount(self) -> None:
        # Start the plan_ready subscriber before showing the screen,
        # so we don't miss the event if the planner finishes quickly.
        asyncio.create_task(self._consume_plan_ready())
        # Also start the planner-text router before showing the screen,
        # for the same reason.
        asyncio.create_task(self._consume_planner_text())

        result = await self.push_screen_wait(self._plan_screen)
        if result is None or (isinstance(result, tuple) and result[0] != "approved"):
            self.exit()
            return

        # Start the rest of the subscriptions and the scenario runner.
        asyncio.create_task(self._consume_session_events())
        asyncio.create_task(self._consume_bug_events())
        asyncio.create_task(self._consume_queue_events())
        asyncio.create_task(self._consume_log())
        asyncio.create_task(self._scenario_runner())

    def action_toggle_log(self) -> None:
        self.log_strip.toggle()

    async def _consume_plan_ready(self) -> None:
        import yaml
        async for ev in self._bus.subscribe("plan_ready"):
            scenarios = ev.data.get("scenarios", [])
            text = yaml.safe_dump({"scenarios": scenarios}, sort_keys=False)
            self._plan_screen.show_plan_for_approval(text)

    async def _consume_planner_text(self) -> None:
        async for ev in self._bus.subscribe("note"):
            if ev.data.get("session_label") == "planner":
                self._plan_screen.append_planner_text(ev.data.get("text", ""))

    async def _consume_session_events(self) -> None:
        async for ev in self._bus.subscribe("*"):
            if ev.type == "process_start" and ev.data.get("session_label", "").startswith("explorer"):
                label = ev.data["session_label"]
                running = next((s for s in self._queue.scenarios()
                                if self._queue.status(s.id).value == "running"), None)
                title = running.title if running else label
                self.sessions_pane.add_session(label, title)
            elif ev.type == "subagent_start":
                self.sessions_pane.add_subagent(
                    ev.data["session_label"], ev.data["tool_use_id"], ev.data["description"])
            elif ev.type == "subagent_end":
                self.sessions_pane.end_subagent(ev.data["tool_use_id"])
            elif ev.type == "process_exit":
                label = ev.data.get("session_label", "")
                rc = ev.data.get("returncode", -1)
                self.sessions_pane.mark_session(label, "done" if rc == 0 else "failed")

    async def _consume_bug_events(self) -> None:
        async for ev in self._bus.subscribe("bug_filed"):
            self.bugs_pane.refresh_from_store()
            self.header.bug_count = self._bugs.count()

    async def _consume_queue_events(self) -> None:
        async for ev in self._bus.subscribe("*"):
            if ev.type in ("scenario_proposed", "scenario_start", "scenario_done"):
                self.header.pending = self._queue.pending_count()
                self.header.discovered = self._queue.discovered_count()

    async def _consume_log(self) -> None:
        async for ev in self._bus.subscribe("note"):
            label = ev.data.get("session_label", "?")
            self.log_strip.append(f"{label}: {ev.data.get('text', '')[:120]}")
