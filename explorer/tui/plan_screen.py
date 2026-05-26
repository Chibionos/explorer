from __future__ import annotations
import asyncio
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, Log, Label

from ..runner.interview_questions import INTERVIEW_QUESTIONS


class PlanScreen(Screen):
    """Three modes:
    - interview: walk through INTERVIEW_QUESTIONS, one at a time
    - waiting: all answers collected, planner subprocess running
    - approval: plan is shown; press y to start exploration
    """

    BINDINGS = [
        ("y", "approve", "approve"),
        ("q", "quit", "quit"),
    ]

    def __init__(self, *, answers_out: asyncio.Queue[list[str]]) -> None:
        super().__init__()
        self._answers_out = answers_out
        self._answers: list[str] = []
        self._q_idx = 0
        self._mode = "interview"
        self._plan_yaml_text = ""
        self._preloaded_plan: str | None = None
        self._auto_approve_plan: str | None = None

    def set_preloaded_plan(self, plan_yaml_text: str) -> None:
        """Skip the interview, jump straight to approval with this plan."""
        self._preloaded_plan = plan_yaml_text

    def set_auto_approve(self, plan_yaml_text: str) -> None:
        """Skip interview AND approval — exploration starts immediately."""
        self._auto_approve_plan = plan_yaml_text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Test plan setup — answer 4 short questions, then review the plan.")
            self.transcript = Log(highlight=True)
            yield self.transcript
            self.input = Input(placeholder="Type your answer and press Enter…")
            yield self.input

    def on_mount(self) -> None:
        if self._auto_approve_plan is not None:
            # Pre-made plan + --yes: dismiss immediately as approved.
            self.call_after_refresh(
                self.dismiss, ("approved", self._auto_approve_plan)
            )
            return
        if self._preloaded_plan is not None:
            # Pre-made plan, manual approval: jump straight to approval mode.
            self.input.disabled = True
            self.show_plan_for_approval(self._preloaded_plan)
            return
        self._ask_next()

    def _ask_next(self) -> None:
        if self._q_idx < len(INTERVIEW_QUESTIONS):
            q = INTERVIEW_QUESTIONS[self._q_idx]
            self.transcript.write_line("")
            self.transcript.write_line(f"Q{self._q_idx + 1}/{len(INTERVIEW_QUESTIONS)}: {q}")
        else:
            self._mode = "waiting"
            self.transcript.write_line("")
            self.transcript.write_line("Generating plan… (this calls Claude once; usually 5-30 seconds)")
            self.input.disabled = True
            self._answers_out.put_nowait(self._answers)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._mode != "interview":
            return
        text = event.value.strip()
        if not text:
            return
        self.transcript.write_line(f"> {text}")
        self._answers.append(text)
        self._q_idx += 1
        self.input.value = ""
        self._ask_next()

    def append_planner_text(self, text: str) -> None:
        # Show planner thinking/output to the user (notes from the subprocess).
        self.transcript.write_line(text)

    def show_plan_for_approval(self, plan_yaml_text: str) -> None:
        self._mode = "approval"
        self._plan_yaml_text = plan_yaml_text
        self.transcript.write_line("")
        self.transcript.write_line("=== PROPOSED PLAN ===")
        self.transcript.write_line(plan_yaml_text)
        self.transcript.write_line("")
        self.transcript.write_line("Press y to approve and start exploration, q to quit.")

    def action_approve(self) -> None:
        if self._mode == "approval":
            self.dismiss(("approved", self._plan_yaml_text))

    def action_quit(self) -> None:
        self.dismiss(("cancelled", None))
