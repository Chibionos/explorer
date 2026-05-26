from __future__ import annotations
from textual.reactive import reactive
from textual.widget import Widget


class Header(Widget):
    bug_count: reactive[int] = reactive(0)
    pending: reactive[int] = reactive(0)
    discovered: reactive[int] = reactive(0)
    jira_project: reactive[str] = reactive("?")
    epic_key: reactive[str] = reactive("?")
    codebase_path: reactive[str] = reactive("?")
    health: reactive[str] = reactive("idle")

    def render(self) -> str:
        return (
            f"explorer ─ Bugs: {self.bug_count} │ Pending: {self.pending} │ "
            f"Discovered: {self.discovered} │ {self.health} │ "
            f"Jira: {self.jira_project} / Epic {self.epic_key} │ "
            f"Code: {self.codebase_path}"
        )
