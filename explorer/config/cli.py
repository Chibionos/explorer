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
    plan: str | None
    yes: bool
    continuous: bool
    resume: str | None
    pick_tab: bool
    confluence_space: str | None
    confluence_page: str | None


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--jira-project",
                   help="Jira project key for bug filing (e.g. AE). Required on first run.")
    p.add_argument("--epic",
                   help="Jira epic key under which to file bugs. Required on first run.")
    p.add_argument("--codebase",
                   help="Path to the product source tree. Required on first run.")
    p.add_argument("--tab-url",
                   help="The browser tab URL the explorer should target. If omitted, "
                        "the TUI shows a tab picker on startup.")
    p.add_argument("--bu-name",
                   help="browser-harness daemon name (default: harness default).")
    p.add_argument("--plan",
                   help="Path to a YAML file with pre-made scenarios "
                        "(skips the in-TUI planner / interview).")
    p.add_argument("-y", "--yes", action="store_true",
                   help="When --plan is given, auto-approve and skip the approval screen.")
    p.add_argument("--continuous", action="store_true",
                   help="Keep exploring after the initial plan finishes: "
                        "requeue every original scenario as a fresh round. Press q to stop.")
    p.add_argument("--resume", nargs="?", const="latest", default=None,
                   help="Continue a previous run. Pass 'latest' or omit the value to pick "
                        "the most recent run, or pass a specific run directory or timestamp.")
    p.add_argument("--pick-tab", action="store_true",
                   help="Force the tab picker even when a tab is configured.")
    p.add_argument("--confluence-space",
                   help="Confluence space key (e.g. ENG). When given, a new Confluence "
                        "page is created per run and updated as scenarios complete.")
    p.add_argument("--confluence-page",
                   help="Existing Confluence page ID. When given, scenarios are appended "
                        "to this page (persistent evidence log across runs).")


def parse_args(argv: list[str]) -> CliArgs:
    p = argparse.ArgumentParser(
        prog="explorer",
        description=(
            "Claude Code exploratory tester for web apps. Drives a real Chrome tab "
            "via browser-harness, spawns Claude subprocesses per scenario, files "
            "Jira bugs with code-aware fix suggestions, optionally records evidence "
            "to a Confluence page. Subcommands: 'status' for a one-shot summary of "
            "the current/latest run; 'tail' to stream events live."),
    )
    _add_run_args(p)
    ns = p.parse_args(argv)
    return CliArgs(
        jira_project=ns.jira_project, epic=ns.epic,
        codebase=ns.codebase, tab_url=ns.tab_url, bu_name=ns.bu_name,
        plan=ns.plan, yes=ns.yes, continuous=ns.continuous,
        resume=ns.resume, pick_tab=ns.pick_tab,
        confluence_space=ns.confluence_space, confluence_page=ns.confluence_page,
    )


def resolve_config(args: CliArgs, project_dir: Path) -> ProjectConfig:
    disk = load(project_dir / ".explorer" / "project.yaml")
    if disk is not None:
        merged = disk.merge(
            jira_project=args.jira_project, epic_key=args.epic,
            codebase_path=args.codebase, tab_url=args.tab_url,
            bu_name=args.bu_name,
            confluence_space=args.confluence_space,
            confluence_page=args.confluence_page,
        )
        save(merged, project_dir / ".explorer" / "project.yaml")
        return merged

    # --tab-url is optional: when missing, the TUI shows a tab picker.
    missing = [name for name, v in (
        ("--jira-project", args.jira_project),
        ("--epic", args.epic),
        ("--codebase", args.codebase),
    ) if v is None]
    if missing:
        print(f"first run requires: {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)

    cfg = ProjectConfig(
        jira_project=args.jira_project, epic_key=args.epic,
        codebase_path=args.codebase, tab_url=args.tab_url,
        bu_name=args.bu_name,
        confluence_space=args.confluence_space,
        confluence_page=args.confluence_page,
    )
    save(cfg, project_dir / ".explorer" / "project.yaml")
    return cfg
