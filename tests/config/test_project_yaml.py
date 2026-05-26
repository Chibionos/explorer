from pathlib import Path
from explorer.config.project_yaml import ProjectConfig, load, save


def test_save_then_load_roundtrip(tmp_path: Path):
    cfg = ProjectConfig(
        jira_project="ABC", epic_key="ABC-1042",
        codebase_paths=[str(tmp_path / "code")],
        tab_url="https://app.example.com", bu_name=None,
    )
    save(cfg, tmp_path / ".explorer/project.yaml")
    loaded = load(tmp_path / ".explorer/project.yaml")
    assert loaded == cfg


def test_load_missing_returns_none(tmp_path: Path):
    assert load(tmp_path / "nope.yaml") is None


def test_merge_overrides_keeps_existing(tmp_path: Path):
    cfg = ProjectConfig(
        jira_project="ABC", epic_key="ABC-1", codebase_paths=["/c"],
        tab_url="u", bu_name=None,
    )
    merged = cfg.merge(jira_project=None, epic_key="ABC-2", codebase_paths=None,
                       tab_url=None, bu_name="work")
    assert merged.jira_project == "ABC"
    assert merged.epic_key == "ABC-2"
    assert merged.bu_name == "work"


def test_primary_codebase_property():
    cfg = ProjectConfig(
        jira_project="ABC", epic_key="ABC-1",
        codebase_paths=["/repo/a", "/repo/b", "/repo/c"],
        tab_url=None, bu_name=None,
    )
    assert cfg.primary_codebase == "/repo/a"
