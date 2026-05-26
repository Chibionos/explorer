from __future__ import annotations
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import ListView, ListItem, Static, Label

from ..runner.tabs import ChromeTab


class TabPickerScreen(Screen):
    """Pick the browser tab the explorer should target.

    Dismisses with the chosen ChromeTab, or None if cancelled.
    """

    BINDINGS = [
        ("enter", "select", "select"),
        ("escape", "cancel", "cancel"),
        ("q", "cancel", "cancel"),
        ("r", "refresh", "refresh list"),
    ]

    def __init__(self, *, tabs: list[ChromeTab], current_url: str | None = None) -> None:
        super().__init__()
        self._tabs = tabs
        self._current_url = current_url

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                f"Pick the browser tab to target ({len(self._tabs)} open).  "
                "↑↓ to move, Enter to select, q to cancel, r to refresh."
            )
            self.list = ListView()
            yield self.list
            yield Label(
                "After selection the chosen tab's URL is what the explorer "
                "will verify against at the start of each scenario.",
                classes="muted",
            )

    def on_mount(self) -> None:
        self._populate()

    def _populate(self) -> None:
        self.list.clear()
        preselect_idx = 0
        for i, tab in enumerate(self._tabs):
            title = (tab.title or "(untitled)")[:120]
            url = tab.url[:160]
            marker = "→ " if tab.url == self._current_url else "  "
            self.list.append(ListItem(Static(f"{marker}{title}\n     {url}")))
            if tab.url == self._current_url:
                preselect_idx = i
        if self._tabs:
            self.list.index = preselect_idx

    def action_select(self) -> None:
        idx = self.list.index
        if idx is None or idx < 0 or idx >= len(self._tabs):
            return
        self.dismiss(self._tabs[idx])

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def action_refresh(self) -> None:
        from ..runner.tabs import list_chrome_tabs
        self._tabs = await list_chrome_tabs()
        self._populate()
