from __future__ import annotations
from textual.widgets import Tree


class SessionsPane(Tree):
    """Expandable tree of scenarios, with per-scenario activity timelines.

    Each scenario (top-level node) is collapsed by default. Expanding it
    reveals a chronological timeline:
      ▶ scenario_start
      📝 narrative text (assistant reasoning between actions)
      🌐 browser-harness calls
      📄/🔍/✏️  file ops
      📋 mcp__atlassian__* calls
      → Task: <subagent description>      (nested ✓ on completion)
      ‼ bug_observed: <title>
      ✓ bug_filed: AE-1234 <title>
      ✓ scenario_done
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__("Sessions", id=id)
        self.show_root = False
        self._session_nodes: dict = {}      # session_label -> tree node
        self._subagent_nodes: dict = {}     # tool_use_id -> tree node (Task children)

    # ---- session lifecycle ----

    def add_session(self, session_label: str, title: str) -> None:
        # Collapsed by default; expanded view fills in as events arrive.
        node = self.root.add(f"⏵ {session_label} — {title}", expand=False)
        self._session_nodes[session_label] = node

    def mark_session(self, session_label: str, status: str) -> None:
        node = self._session_nodes.get(session_label)
        if not node:
            return
        icon = {"done": "✓", "failed": "✗", "running": "⏵"}.get(status, "·")
        current = node.label.plain
        rest = current.split(" ", 1)[1] if " " in current else current
        node.set_label(f"{icon} {rest}")

    # ---- per-action timeline entries ----

    def add_action(self, session_label: str, summary: str) -> None:
        """Tool call leaf (Bash/Read/Grep/Write/MCP/etc.)."""
        parent = self._session_nodes.get(session_label)
        if parent:
            parent.add_leaf(summary[:180])

    def add_narrative(self, session_label: str, text: str) -> None:
        """Assistant text between tool calls — the agent's reasoning."""
        parent = self._session_nodes.get(session_label)
        if parent:
            parent.add_leaf(f"📝 {text[:160]}")

    def add_scenario_event(self, session_label: str, kind: str, text: str) -> None:
        """Lifecycle / bug events for the session."""
        parent = self._session_nodes.get(session_label)
        if not parent:
            return
        prefix = {
            "scenario_start": "▶  start",
            "scenario_done":  "✓  done",
            "bug_observed":   "‼  observed",
            "bug_filed":      "→  filed",
            "bug_dup_comment": "→  dup-comment",
            "scenario_proposed": "+  proposed",
            "confluence_updated": "📋 confluence",
        }.get(kind, kind)
        parent.add_leaf(f"{prefix}: {text[:160]}")

    # ---- Task sub-agents (Claude's Task tool) ----

    def add_subagent(self, session_label: str, tool_use_id: str, description: str) -> None:
        parent = self._session_nodes.get(session_label)
        if not parent:
            return
        sub = parent.add(f"⏵ Task — {description[:120]}", expand=False)
        self._subagent_nodes[tool_use_id] = sub

    def end_subagent(self, tool_use_id: str, *, error: bool = False) -> None:
        sub = self._subagent_nodes.get(tool_use_id)
        if not sub:
            return
        current = sub.label.plain
        rest = current.split(" ", 1)[1] if " " in current else current
        icon = "✗" if error else "✓"
        sub.set_label(f"{icon} {rest}")
