from __future__ import annotations
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from .project_yaml import ProjectConfig, load, save


@dataclass
class CliArgs:
    jira_project: str | None
    epic: str | None
    codebase: str | None
    tab_url: str | None
    bu_name: str | None


def parse_args(argv: list[str]) -> CliArgs:
    p = argparse.ArgumentParser(prog="explorer")
    p.add_argument("--jira-project")
    p.add_argument("--epic")
    p.add_argument("--codebase")
    p.add_argument("--tab-url")
    p.add_argument("--bu-name")
    ns = p.parse_args(argv)
    return CliArgs(jira_project=ns.jira_project, epic=ns.epic,
                   codebase=ns.codebase, tab_url=ns.tab_url, bu_name=ns.bu_name)


def resolve_config(args: CliArgs, project_dir: Path) -> ProjectConfig:
    disk = load(project_dir / ".explorer" / "project.yaml")
    if disk is not None:
        merged = disk.merge(jira_project=args.jira_project, epic_key=args.epic,
                            codebase_path=args.codebase, tab_url=args.tab_url,
                            bu_name=args.bu_name)
        save(merged, project_dir / ".explorer" / "project.yaml")
        return merged

    missing = [name for name, v in (
        ("--jira-project", args.jira_project),
        ("--epic", args.epic),
        ("--codebase", args.codebase),
        ("--tab-url", args.tab_url),
    ) if v is None]
    if missing:
        print(f"first run requires: {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)

    cfg = ProjectConfig(jira_project=args.jira_project, epic_key=args.epic,
                        codebase_path=args.codebase, tab_url=args.tab_url,
                        bu_name=args.bu_name)
    save(cfg, project_dir / ".explorer" / "project.yaml")
    return cfg
