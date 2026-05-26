import json
from pathlib import Path
from explorer.core.bug_store import BugStore, Bug


def test_add_appends_and_persists(tmp_path: Path):
    mirror = tmp_path / "bugs.json"
    store = BugStore(mirror_path=mirror)
    bug = Bug(uuid="u1", jira_key="ABC-1", title="t", scenario_id="s1",
              screenshot_path=str(tmp_path / "s.png"), jira_url="https://j/ABC-1")
    store.add(bug)
    assert store.count() == 1
    saved = json.loads(mirror.read_text())
    assert saved[0]["jira_key"] == "ABC-1"


def test_newest_first(tmp_path: Path):
    store = BugStore(mirror_path=tmp_path / "bugs.json")
    store.add(Bug(uuid="u1", jira_key="A", title="first", scenario_id="s",
                  screenshot_path="", jira_url=""))
    store.add(Bug(uuid="u2", jira_key="B", title="second", scenario_id="s",
                  screenshot_path="", jira_url=""))
    bugs = store.list_newest_first()
    assert bugs[0].jira_key == "B"
    assert bugs[1].jira_key == "A"


def test_count(tmp_path: Path):
    store = BugStore(mirror_path=tmp_path / "bugs.json")
    assert store.count() == 0
    store.add(Bug(uuid="u1", jira_key="A", title="t", scenario_id="s",
                  screenshot_path="", jira_url=""))
    assert store.count() == 1
