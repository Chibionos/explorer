from pathlib import Path
import pytest
import yaml
from explorer.config.cli import parse_args, resolve_config
from explorer.config.project_yaml import ProjectConfig, save


def test_parse_args_all_flags():
    args = parse_args([
        "--jira-project", "ABC",
        "--epic", "ABC-1042",
        "--codebase", "/home/u/code",
        "--tab-url", "https://app.example.com",
        "--bu-name", "work",
    ])
    assert args.jira_project == "ABC"
    assert args.epic == "ABC-1042"
    assert args.codebases == ["/home/u/code"]


def test_parse_args_multiple_codebases():
    args = parse_args([
        "--jira-project", "ABC",
        "--epic", "ABC-1042",
        "--codebase", "/repo/frontend",
        "--codebase", "/repo/backend",
        "--codebase", "/repo/shared",
    ])
    assert args.codebases == ["/repo/frontend", "/repo/backend", "/repo/shared"]


def test_resolve_uses_disk_when_flags_omitted(tmp_path: Path):
    disk_cfg = ProjectConfig(
        jira_project="ABC", epic_key="ABC-1", codebase_paths=["/c"],
        tab_url="u", bu_name=None,
    )
    save(disk_cfg, tmp_path / ".explorer/project.yaml")
    args = parse_args([])
    cfg = resolve_config(args, project_dir=tmp_path)
    assert cfg == disk_cfg


def test_resolve_first_run_requires_all_flags(tmp_path: Path):
    args = parse_args(["--jira-project", "ABC"])
    with pytest.raises(SystemExit):
        resolve_config(args, project_dir=tmp_path)


def test_resolve_flags_override_disk(tmp_path: Path):
    save(ProjectConfig(jira_project="ABC", epic_key="ABC-1", codebase_paths=["/c"],
                       tab_url="u", bu_name=None),
         tmp_path / ".explorer/project.yaml")
    args = parse_args(["--epic", "ABC-2"])
    cfg = resolve_config(args, project_dir=tmp_path)
    assert cfg.epic_key == "ABC-2"
    assert cfg.jira_project == "ABC"


def test_resolve_first_run_persists_multi_codebases(tmp_path: Path):
    args = parse_args([
        "--jira-project", "ABC",
        "--epic", "ABC-1",
        "--codebase", "/repo/a",
        "--codebase", "/repo/b",
    ])
    cfg = resolve_config(args, project_dir=tmp_path)
    assert cfg.codebase_paths == ["/repo/a", "/repo/b"]
    # And it persisted to disk.
    on_disk = yaml.safe_load((tmp_path / ".explorer/project.yaml").read_text())
    assert on_disk["codebase_paths"] == ["/repo/a", "/repo/b"]


def test_old_project_yaml_migrates_codebase_path(tmp_path: Path):
    """An old project.yaml with `codebase_path: <str>` still loads cleanly."""
    p = tmp_path / ".explorer/project.yaml"
    p.parent.mkdir(parents=True)
    p.write_text(yaml.safe_dump({
        "jira_project": "ABC",
        "epic_key": "ABC-1",
        "codebase_path": "/old/single/path",
        "tab_url": "u",
        "bu_name": None,
    }))
    args = parse_args([])
    cfg = resolve_config(args, project_dir=tmp_path)
    assert cfg.codebase_paths == ["/old/single/path"]
    assert cfg.primary_codebase == "/old/single/path"
