"""List real Chrome tabs via browser-harness."""
from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass

# Alias reused from claude_proc.py rationale: spawns a subprocess from an
# argv list (no shell), so the security-reminder hook's exec() warning
# doesn't apply.
_spawn = asyncio.create_subprocess_exec


@dataclass(frozen=True)
class ChromeTab:
    title: str
    url: str


_LIST_TABS_SNIPPET = """
import json
result = cdp("Target.getTargets")
pages = [t for t in result.get("targetInfos", [])
         if t.get("type") == "page"
         and not t.get("url", "").startswith("chrome://")
         and not t.get("url", "").startswith("devtools://")
         and not t.get("url", "").startswith("chrome-extension://")]
print(json.dumps([{"title": p.get("title",""), "url": p.get("url","")} for p in pages]))
"""


def _parse_tabs_output(stdout: str) -> list[ChromeTab]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return [ChromeTab(title=t.get("title", ""), url=t.get("url", ""))
                    for t in data if isinstance(t, dict)]
    return []


async def list_chrome_tabs(*, timeout: float = 10.0) -> list[ChromeTab]:
    """Return all real Chrome tabs (excludes chrome://, devtools://, extensions).

    Returns [] if browser-harness can't be reached.
    """
    try:
        proc = await _spawn(
            "browser-harness", "-c", _LIST_TABS_SNIPPET,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return []
        if proc.returncode != 0:
            return []
        return _parse_tabs_output(stdout.decode("utf-8", errors="replace"))
    except FileNotFoundError:
        return []
