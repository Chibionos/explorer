from __future__ import annotations
from collections import deque
from textual.reactive import reactive
from textual.widget import Widget


class LogStrip(Widget):
    expanded: reactive[bool] = reactive(False)

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._lines: deque[str] = deque(maxlen=40)

    def append(self, line: str) -> None:
        self._lines.append(line)
        self.refresh()

    def toggle(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.add_class("expanded")
        else:
            self.remove_class("expanded")

    def render(self) -> str:
        if not self._lines:
            return "(idle)"
        # By default show last 8 lines; e expands to all 40.
        n = 20 if self.expanded else 8
        return "\n".join(list(self._lines)[-n:])
