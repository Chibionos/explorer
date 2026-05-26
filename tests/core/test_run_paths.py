from pathlib import Path
from explorer.core.run_paths import RunPaths


def test_creates_directory_structure(tmp_path: Path):
    rp = RunPaths.new(base=tmp_path)
    assert rp.root.exists()
    assert rp.screenshots_dir.exists()


def test_paths_under_runs_subdir(tmp_path: Path):
    rp = RunPaths.new(base=tmp_path)
    assert rp.root.parent.name == "runs"


def test_path_names(tmp_path: Path):
    rp = RunPaths.new(base=tmp_path)
    assert rp.plan_yaml.name == "plan.yaml"
    assert rp.events_log.name == "events.jsonl"
    assert rp.bugs_json.name == "bugs.json"
    assert rp.event_log_for_subprocess.name == "explorer_event_log.jsonl"
