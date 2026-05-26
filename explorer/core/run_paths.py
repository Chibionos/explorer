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

    @classmethod
    def existing(cls, root: Path) -> "RunPaths":
        """Reuse an existing run directory (for --resume)."""
        if not root.exists():
            raise FileNotFoundError(f"run dir not found: {root}")
        (root / "screenshots").mkdir(exist_ok=True)
        return cls(root=root)

    @classmethod
    def latest(cls, base: Path) -> "RunPaths | None":
        """Find the most recent run dir under base/runs/, or None."""
        runs_dir = base / "runs"
        if not runs_dir.exists():
            return None
        candidates = sorted([p for p in runs_dir.iterdir() if p.is_dir()],
                            reverse=True)
        if not candidates:
            return None
        return cls.existing(candidates[0])

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
