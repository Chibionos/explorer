from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Bug:
    uuid: str
    jira_key: str
    title: str
    scenario_id: str
    screenshot_path: str
    jira_url: str


class BugStore:
    def __init__(self, mirror_path: Path) -> None:
        self._mirror = mirror_path
        self._mirror.parent.mkdir(parents=True, exist_ok=True)
        self._bugs: list[Bug] = []

    def add(self, bug: Bug) -> None:
        self._bugs.append(bug)
        self._persist()

    def count(self) -> int:
        return len(self._bugs)

    def list_newest_first(self) -> list[Bug]:
        return list(reversed(self._bugs))

    def _persist(self) -> None:
        self._mirror.write_text(json.dumps([asdict(b) for b in self._bugs], indent=2))
