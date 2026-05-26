from __future__ import annotations
import asyncio
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, Log, Label


class PlanScreen(Screen):
    BINDINGS = [
        ("y", "approve", "approve"),
        ("q", "quit", "quit"),
    ]

    def __init__(self, *, answers: asyncio.Queue[str]) -> None:
        super().__init__()
        self._answers = answers
        self._mode = "interview"
        self._plan_yaml_text = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Planner interview — answer questions one at a time, then approve the plan.")
            self.transcript = Log(highlight=True)
            yield self.transcript
            self.input = Input(placeholder="Type your answer and press Enter…")
            yield self.input

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._mode != "interview":
            return
        text = event.value.strip()
        self.transcript.write_line(f"> {text}")
        self._answers.put_nowait(text)
        self.input.value = ""

    def append_planner_text(self, text: str) -> None:
        self.transcript.write_line(text)

    def show_plan_for_approval(self, plan_yaml_text: str) -> None:
        self._mode = "approval"
        self._plan_yaml_text = plan_yaml_text
        self.transcript.write_line("")
        self.transcript.write_line("=== PROPOSED PLAN ===")
        self.transcript.write_line(plan_yaml_text)
        self.transcript.write_line("Press y to approve, q to quit.")
        self.input.disabled = True

    def action_approve(self) -> None:
        if self._mode == "approval":
            self.dismiss(("approved", self._plan_yaml_text))

    def action_quit(self) -> None:
        self.dismiss(("cancelled", None))
