from __future__ import annotations
from textual.widgets import ListView, ListItem, Static
from ..core.bug_store import BugStore


class BugsPane(ListView):
    def __init__(self, store: BugStore) -> None:
        super().__init__()
        self._store = store

    def refresh_from_store(self) -> None:
        self.clear()
        for bug in self._store.list_newest_first():
            self.append(ListItem(Static(f"{bug.jira_key}  {bug.title}")))
