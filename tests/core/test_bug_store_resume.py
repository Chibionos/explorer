import json
from pathlib import Path
from explorer.core.bug_store import BugStore, Bug


def test_bug_store_loads_existing_mirror(tmp_path: Path):
    mirror = tmp_path / "bugs.json"
    mirror.write_text(json.dumps([
        {"uuid": "u1", "jira_key": "ABC-1", "title": "Save fails",
         "scenario_id": "s1", "screenshot_path": "/x.png",
         "jira_url": "https://j/ABC-1"},
        {"uuid": "u2", "jira_key": "ABC-2", "title": "Modal broken",
         "scenario_id": "s2", "screenshot_path": "/y.png",
         "jira_url": "https://j/ABC-2"},
    ]))
    store = BugStore(mirror_path=mirror)
    assert store.count() == 2
    all_bugs = store.all()
    assert all_bugs[0].jira_key == "ABC-1"
    assert all_bugs[1].title == "Modal broken"


def test_bug_store_handles_missing_mirror(tmp_path: Path):
    store = BugStore(mirror_path=tmp_path / "absent.json")
    assert store.count() == 0


def test_bug_store_handles_corrupt_mirror(tmp_path: Path):
    mirror = tmp_path / "corrupt.json"
    mirror.write_text("not json")
    store = BugStore(mirror_path=mirror)
    assert store.count() == 0  # falls back, doesn't crash


def test_bug_store_persists_appended_bugs_after_load(tmp_path: Path):
    mirror = tmp_path / "bugs.json"
    mirror.write_text(json.dumps([
        {"uuid": "u1", "jira_key": "ABC-1", "title": "Original",
         "scenario_id": "s1", "screenshot_path": "", "jira_url": ""},
    ]))
    store = BugStore(mirror_path=mirror)
    store.add(Bug(uuid="u2", jira_key="ABC-2", title="New",
                  scenario_id="s2", screenshot_path="", jira_url=""))
    saved = json.loads(mirror.read_text())
    assert len(saved) == 2
    assert saved[0]["jira_key"] == "ABC-1"
    assert saved[1]["jira_key"] == "ABC-2"
