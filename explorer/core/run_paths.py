from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class RunPaths:
    root: Path

    @classmethod
    def new(cls, base: Path) -> "RunPaths":
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        root = base / "runs" / stamp
        root.mkdir(parents=True, exist_ok=True)
        (root / "screenshots").mkdir(exist_ok=True)
        return cls(root=root)

    @property
    def screenshots_dir(self) -> Path:
        return self.root / "screenshots"

    @property
    def plan_yaml(self) -> Path:
        return self.root / "plan.yaml"

    @property
    def events_log(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def bugs_json(self) -> Path:
        return self.root / "bugs.json"

    @property
    def event_log_for_subprocess(self) -> Path:
        return self.root / "explorer_event_log.jsonl"
