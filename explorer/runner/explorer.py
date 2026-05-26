from __future__ import annotations
from pathlib import Path
from ..core.event_bus import EventBus
from ..core.dedup import DedupIndex
from ..core.scenario_queue import Scenario
from .claude_proc import run_claude


PROMPTS_DIR = Path(__file__).parent / "prompts"


def _substitute(template: str, vars: dict[str, str]) -> str:
    out = template
    for k, v in vars.items():
        out = out.replace("{{" + k + "}}", v)
    return out


async def run_explorer(
    *, scenario: Scenario, codebase_path: Path, event_log: Path,
    screenshots_dir: Path, jira_project: str, epic_key: str,
    dedup: DedupIndex, bus: EventBus, session_label: str,
    tab_url: str | None = None,
    bu_name: str | None = None,
) -> int:
    template = (PROMPTS_DIR / "system_explorer.md").read_text()
    known = "; ".join(f"{k}: {t}" for k, t in dedup.titles_for_prompt()) or "(none yet)"
    prompt = _substitute(template, {
        "SCENARIO_ID": scenario.id,
        "SCENARIO_TITLE": scenario.title,
        "SCENARIO_GOAL": scenario.goal,
        "JIRA_PROJECT": jira_project,
        "EPIC_KEY": epic_key,
        "KNOWN_BUG_TITLES": known,
        "TAB_URL": tab_url or "(none — verify the current tab looks like an app under test)",
    })
    env = {
        "EXPLORER_EVENT_LOG": str(event_log),
        "SCREENSHOTS_DIR": str(screenshots_dir),
        "BUG_FILER_PROMPT_PATH": str(PROMPTS_DIR / "system_bug_filer.md"),
        "PROPOSER_PROMPT_PATH": str(PROMPTS_DIR / "system_proposer.md"),
        "JIRA_PROJECT": jira_project,
        "EPIC_KEY": epic_key,
    }
    if bu_name:
        env["BU_NAME"] = bu_name
    return await run_claude(prompt=prompt, cwd=codebase_path,
                            env_overrides=env, bus=bus, session_label=session_label)
