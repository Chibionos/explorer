from __future__ import annotations
from pathlib import Path
from ..core.event_bus import EventBus
from .claude_proc import run_claude
from .interview_questions import INTERVIEW_QUESTIONS


PROMPTS_DIR = Path(__file__).parent / "prompts"


def _format_answers(answers: list[str]) -> str:
    out = []
    for i, (q, a) in enumerate(zip(INTERVIEW_QUESTIONS, answers), start=1):
        out.append(f"Q{i}: {q}\nA{i}: {a}\n")
    return "\n".join(out)


async def run_planner_with_answers(
    *, answers: list[str], event_log: Path, bus: EventBus, codebase_path: Path,
) -> int:
    """Build the planner prompt from collected answers, run claude once, exit."""
    template = (PROMPTS_DIR / "system_planner.md").read_text()
    prompt = template.replace("{{ANSWERS}}", _format_answers(answers))
    env = {"EXPLORER_EVENT_LOG": str(event_log)}
    return await run_claude(
        prompt=prompt, cwd=codebase_path,
        env_overrides=env, bus=bus, session_label="planner",
    )
