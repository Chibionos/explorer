from __future__ import annotations
import asyncio
from typing import Awaitable, Callable
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual import work

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
from .tab_picker import TabPickerScreen
from ..runner.tabs import list_chrome_tabs


class ExplorerApp(App):
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        ("q", "quit", "quit"),
        ("e", "toggle_log", "expand log"),
        ("t", "pick_tab", "pick tab"),
        ("r", "restart_current", "restart current explorer"),
    ]

    def __init__(
        self, *, cfg: ProjectConfig, bus: EventBus, queue: ScenarioQueue,
        bugs: BugStore, run_paths: RunPaths,
        plan_screen: PlanScreen,
        scenario_runner: Callable[[], Awaitable[None]],
        force_tab_picker: bool = False,
        on_tab_changed: Callable[[str], None] | None = None,
        restart_current: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._bus = bus
        self._queue = queue
        self._bugs = bugs
        self._run_paths = run_paths
        self._plan_screen = plan_screen
        self._scenario_runner = scenario_runner
        self._tab_url: str | None = cfg.tab_url
        self._force_tab_picker = force_tab_picker
        self._on_tab_changed = on_tab_changed
        self._restart_current = restart_current
        # session_label -> scenario_id (so scenario events route to the right tree node)
        self._scenario_for_session: dict[str, str] = {}
        self._session_for_scenario: dict[str, str] = {}
        # Health tracking: seconds since last activity from a session.
        # Updated every tool_action / narrative / note / sub-agent event.
        import time
        self._time = time
        self._last_activity_at: dict[str, float] = {}
        # Pending sub-agent labels (used to render sub-counts in header)
        self._active_sessions: set[str] = set()

    def current_tab_url(self) -> str | None:
        """Read by the runner before each scenario; reflects latest user pick."""
        return self._tab_url

    def compose(self) -> ComposeResult:
        self.header = Header(id="header")
        self.header.jira_project = self._cfg.jira_project
        self.header.epic_key = self._cfg.epic_key
        paths = self._cfg.codebase_paths
        self.header.codebase_path = paths[0] if len(paths) == 1 else f"{paths[0]} (+{len(paths)-1})"
        yield self.header
        self.sessions_pane = SessionsPane(id="sessions")
        self.bugs_pane = BugsPane(self._bugs, id="bugs")
        with Horizontal():
            yield self.sessions_pane
            yield self.bugs_pane
        self.log_strip = LogStrip(id="log")
        yield self.log_strip

    def on_mount(self) -> None:
        # Start the plan_ready subscriber and planner-text router BEFORE
        # the plan screen is pushed, so neither misses an event if the
        # planner finishes quickly.
        asyncio.create_task(self._consume_plan_ready())
        asyncio.create_task(self._consume_planner_text())
        # Textual requires push_screen_wait to run inside a worker.
        self._show_pickers_and_start()

    @work
    async def _show_pickers_and_start(self) -> None:
        # If we don't have a tab URL yet, or the user forced --pick-tab,
        # show the tab picker first.
        if self._tab_url is None or self._force_tab_picker:
            tabs = await list_chrome_tabs()
            if tabs:
                picked = await self.push_screen_wait(
                    TabPickerScreen(tabs=tabs, current_url=self._tab_url))
                if picked is None:
                    self.exit()
                    return
                self._tab_url = picked.url
                if self._on_tab_changed:
                    self._on_tab_changed(picked.url)
            # If browser-harness returns nothing, fall through with whatever
            # tab_url we already had (may be None); the explorer's first step
            # will then bail and surface a useful note.

        # Plan approval / interview.
        result = await self.push_screen_wait(self._plan_screen)
        if result is None or (isinstance(result, tuple) and result[0] != "approved"):
            self.exit()
            return
        asyncio.create_task(self._consume_session_events())
        asyncio.create_task(self._consume_bug_events())
        asyncio.create_task(self._consume_queue_events())
        asyncio.create_task(self._consume_log())
        asyncio.create_task(self._heartbeat_tick())
        asyncio.create_task(self._scenario_runner())

    def action_restart_current(self) -> None:
        """Kill the currently-running explorer subprocess. The runner loop
        will catch the non-zero exit and either requeue (if scenario_done
        wasn't emitted) or move on."""
        if self._restart_current is None:
            self.log_strip.append("(r) restart not wired")
            return
        self._restart_current()
        self.log_strip.append("(r) sent SIGTERM to current explorer; runner will pick up next")

    @work
    async def action_pick_tab(self) -> None:
        """Mid-run repick. Takes effect on the NEXT scenario the runner starts."""
        tabs = await list_chrome_tabs()
        if not tabs:
            self.log_strip.append("(t) browser-harness returned no tabs")
            return
        picked = await self.push_screen_wait(
            TabPickerScreen(tabs=tabs, current_url=self._tab_url))
        if picked is None:
            return
        self._tab_url = picked.url
        if self._on_tab_changed:
            self._on_tab_changed(picked.url)
        self.log_strip.append(f"(t) tab → {picked.title[:80]}")

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
            label = (ev.data or {}).get("session_label", "")
            # Update last-activity timer for any event with a session_label.
            if label:
                self._last_activity_at[label] = self._time.time()

            if ev.type == "process_start" and label.startswith("explorer"):
                running = next((s for s in self._queue.scenarios()
                                if self._queue.status(s.id).value == "running"), None)
                title = running.title if running else label
                self.sessions_pane.add_session(label, title)
                if running:
                    self._scenario_for_session[label] = running.id
                    self._session_for_scenario[running.id] = label
                self._active_sessions.add(label)
            elif ev.type == "subagent_start":
                self.sessions_pane.add_subagent(
                    label, ev.data["tool_use_id"], ev.data.get("description", ""))
            elif ev.type == "subagent_end":
                self.sessions_pane.end_subagent(
                    ev.data["tool_use_id"], error=ev.data.get("is_error", False))
            elif ev.type == "tool_action":
                self.sessions_pane.add_action(label, ev.data.get("summary", ""))
            elif ev.type == "narrative":
                self.sessions_pane.add_narrative(label, ev.data.get("text", ""))
            elif ev.type == "process_exit":
                rc = ev.data.get("returncode", -1)
                self.sessions_pane.mark_session(label, "done" if rc == 0 else "failed")
                self._active_sessions.discard(label)
            elif ev.type in ("scenario_start", "scenario_done", "bug_observed",
                             "bug_filed", "bug_dup_comment", "scenario_proposed",
                             "confluence_updated"):
                # These events come from the JSONL tailer; route to the session
                # whose scenario_id matches.
                sid = ev.data.get("scenario_id") or ev.data.get("parent_scenario_id")
                target_label = self._session_for_scenario.get(sid or "", "")
                if not target_label:
                    # Fall back to whichever session is currently active.
                    target_label = next(iter(self._active_sessions), "")
                if target_label:
                    text = (ev.data.get("title") or ev.data.get("jira_key")
                            or ev.data.get("id") or ev.data.get("text") or "")
                    if ev.type == "bug_filed":
                        text = f"{ev.data.get('jira_key','')} {ev.data.get('title','')}"
                    self.sessions_pane.add_scenario_event(target_label, ev.type, text)

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

    async def _heartbeat_tick(self) -> None:
        """Once per second, update header health from last-activity timers."""
        while True:
            await asyncio.sleep(1.0)
            now = self._time.time()
            active = [(l, now - t) for l, t in self._last_activity_at.items()
                      if l in self._active_sessions]
            if not active:
                self.header.health = "idle (no explorer)"
                continue
            # Pick the active session with the SHORTEST idle (most recently busy).
            label, age = min(active, key=lambda lt: lt[1])
            if age > 90:
                self.header.health = f"⚠ STUCK {label} ({int(age)}s idle — press r to restart)"
            elif age > 30:
                self.header.health = f"⏳ slow {label} ({int(age)}s idle)"
            else:
                self.header.health = f"⏵ active {label} ({int(age)}s)"
