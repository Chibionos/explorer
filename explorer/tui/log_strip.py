from __future__ import annotations
from collections import deque
from textual.reactive import reactive
from textual.widget import Widget


class LogStrip(Widget):
    expanded: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self._lines: deque[str] = deque(maxlen=10)

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
        if not self.expanded:
            return self._lines[-1]
        return "\n".join(self._lines)
