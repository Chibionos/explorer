from pathlib import Path
import pytest
from explorer.core.run_paths import RunPaths


def test_existing_reuses_directory(tmp_path: Path):
    target = tmp_path / "runs" / "2026-05-26_01-00-00"
    target.mkdir(parents=True)
    rp = RunPaths.existing(target)
    assert rp.root == target
    assert rp.screenshots_dir.exists()


def test_existing_raises_when_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        RunPaths.existing(tmp_path / "nope")


def test_latest_returns_none_when_no_runs(tmp_path: Path):
    assert RunPaths.latest(tmp_path) is None


def test_latest_picks_newest(tmp_path: Path):
    (tmp_path / "runs" / "2026-05-26_01-00-00").mkdir(parents=True)
    (tmp_path / "runs" / "2026-05-26_02-00-00").mkdir(parents=True)
    (tmp_path / "runs" / "2026-05-25_23-00-00").mkdir(parents=True)
    rp = RunPaths.latest(tmp_path)
    assert rp is not None
    assert rp.root.name == "2026-05-26_02-00-00"
