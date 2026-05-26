from __future__ import annotations
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Placeholder

from ..core.event_bus import EventBus
from ..core.bug_store import BugStore
from ..core.scenario_queue import ScenarioQueue
from ..core.run_paths import RunPaths
from ..config.project_yaml import ProjectConfig
from .header import Header
from .log_strip import LogStrip


class ExplorerApp(App):
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        ("q", "quit", "quit"),
        ("e", "toggle_log", "expand log"),
    ]

    def __init__(self, *, cfg: ProjectConfig, bus: EventBus, queue: ScenarioQueue,
                 bugs: BugStore, run_paths: RunPaths) -> None:
        super().__init__()
        self._cfg = cfg
        self._bus = bus
        self._queue = queue
        self._bugs = bugs
        self._run_paths = run_paths

    def compose(self) -> ComposeResult:
        self.header = Header(id="header")
        self.header.jira_project = self._cfg.jira_project
        self.header.epic_key = self._cfg.epic_key
        self.header.codebase_path = self._cfg.codebase_path
        yield self.header
        with Horizontal():
            yield Placeholder(name="SESSIONS", id="sessions")
            yield Placeholder(name="BUGS", id="bugs")
        self.log_strip = LogStrip()
        self.log_strip.id = "log"
        yield self.log_strip

    def action_toggle_log(self) -> None:
        self.log_strip.toggle()
