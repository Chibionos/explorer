from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from pathlib import Path
import yaml


@dataclass(frozen=True)
class ProjectConfig:
    jira_project: str
    epic_key: str
    codebase_path: str
    tab_url: str
    bu_name: str | None

    def merge(self, **overrides) -> "ProjectConfig":
        clean = {k: v for k, v in overrides.items() if v is not None}
        return replace(self, **clean)


def save(cfg: ProjectConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(asdict(cfg), sort_keys=True))


def load(path: Path) -> ProjectConfig | None:
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text())
    return ProjectConfig(**data)
