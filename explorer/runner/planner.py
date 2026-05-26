from __future__ import annotations
from pathlib import Path
from ..core.event_bus import EventBus
from .claude_proc import run_claude


PROMPTS_DIR = Path(__file__).parent / "prompts"


async def run_planner(*, event_log: Path, bus: EventBus, codebase_path: Path) -> int:
    prompt = (PROMPTS_DIR / "system_planner.md").read_text()
    env = {"EXPLORER_EVENT_LOG": str(event_log)}
    return await run_claude(prompt=prompt, cwd=codebase_path,
                            env_overrides=env, bus=bus, session_label="planner")
