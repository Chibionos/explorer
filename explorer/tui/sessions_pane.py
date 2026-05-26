from __future__ import annotations
from textual.widgets import Tree


class SessionsPane(Tree):
    def __init__(self, *, id: str | None = None) -> None:
        super().__init__("Sessions", id=id)
        self.show_root = False
        # NOTE: don't name these `_nodes` — that shadows Textual's internal NodeList.
        self._session_nodes: dict = {}      # session_label -> tree node
        self._subagent_nodes: dict = {}     # tool_use_id -> tree node

    def add_session(self, session_label: str, title: str) -> None:
        node = self.root.add(f"⏵ {session_label} — {title}", expand=True)
        self._session_nodes[session_label] = node

    def mark_session(self, session_label: str, status: str) -> None:
        node = self._session_nodes.get(session_label)
        if not node:
            return
        icon = {"done": "✓", "failed": "✗", "running": "⏵"}.get(status, "·")
        current = node.label.plain
        rest = current.split(" ", 1)[1] if " " in current else current
        node.set_label(f"{icon} {rest}")

    def add_subagent(self, session_label: str, tool_use_id: str, description: str) -> None:
        parent = self._session_nodes.get(session_label)
        if not parent:
            return
        sub = parent.add_leaf(f"⏵ Task — {description}")
        self._subagent_nodes[tool_use_id] = sub

    def end_subagent(self, tool_use_id: str) -> None:
        sub = self._subagent_nodes.get(tool_use_id)
        if sub:
            current = sub.label.plain
            rest = current.split(" ", 1)[1] if " " in current else current
            sub.set_label(f"✓ {rest}")
