from __future__ import annotations
from dataclasses import dataclass, asdict, field, replace
from pathlib import Path
import yaml


@dataclass(frozen=True)
class ProjectConfig:
    jira_project: str
    epic_key: str
    codebase_paths: list[str]                 # repeatable; first is the cwd for subprocesses
    tab_url: str | None
    bu_name: str | None
    confluence_space: str | None = None
    confluence_page: str | None = None

    @property
    def primary_codebase(self) -> str:
        return self.codebase_paths[0]

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
    # Back-compat: old project.yaml stored a single `codebase_path` string.
    if "codebase_path" in data and "codebase_paths" not in data:
        data["codebase_paths"] = [data.pop("codebase_path")]
    return ProjectConfig(**data)
