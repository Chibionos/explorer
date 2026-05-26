# Claude Code Test Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a long-running TUI tool that spawns Claude Code subprocesses to perform exploratory testing of a product, drives a real Chrome tab via browser-harness, and files bugs to a Jira "Bug Explorer" epic via the Atlassian MCP.

**Architecture:** Python+Textual orchestrator process. Serial scenario execution (one explorer `claude` subprocess at a time, browser lock). Each explorer uses Claude Code's `Task` tool to spawn nested bug-filer / scenario-proposer sub-agents inside its own session. Orchestrator parses each explorer's `--output-format stream-json` for nesting visibility and tails a sentinel JSONL file for canonical bug/scenario events. State is in-memory; replay log + bugs mirror on disk per run.

**Tech Stack:** Python 3.11+, `uv` for dep management, Textual for TUI, `pyyaml` for config, `pytest`+`pytest-asyncio` for tests, `httpx` (Jira mock e2e only), `claude` CLI on $PATH, `browser-harness` CLI on $PATH.

**Spec:** `/home/chibionos/r/explorer/docs/superpowers/specs/2026-05-26-test-explorer-design.md`

---

## File Structure

```
explorer/                                    # python package
├── __init__.py
├── __main__.py                              # entry: argparse → config → TUI
│
├── config/
│   ├── __init__.py
│   ├── cli.py                               # argparse: --jira-project, --epic, --codebase, --tab-url, --bu-name
│   └── project_yaml.py                      # load/save .explorer/project.yaml
│
├── core/
│   ├── __init__.py
│   ├── event_bus.py                         # asyncio pub/sub
│   ├── scenario_queue.py                    # pending/in-progress/done sets
│   ├── bug_store.py                         # in-memory list + JSON mirror
│   ├── dedup.py                             # title-signature normalizer + index
│   ├── browser_lock.py                      # asyncio.Lock + helper
│   └── run_paths.py                         # resolve .explorer/runs/<ts>/{plan.yaml, events.jsonl, bugs.json, screenshots/}
│
├── runner/
│   ├── __init__.py
│   ├── claude_proc.py                       # spawn `claude --output-format stream-json`, parse, emit
│   ├── event_log_tailer.py                  # tail $EXPLORER_EVENT_LOG, emit
│   ├── planner.py                           # planner subprocess driver
│   ├── explorer.py                          # explorer subprocess driver per scenario
│   ├── interview.py                         # interactive variant (stdin from user)
│   └── prompts/
│       ├── system_planner.md
│       ├── system_explorer.md
│       ├── system_bug_filer.md
│       └── system_proposer.md
│
└── tui/
    ├── __init__.py
    ├── app.py                               # Textual App; wires panes + keys
    ├── header.py                            # reactive counters
    ├── sessions_pane.py                     # Tree widget
    ├── bugs_pane.py                         # ListView widget
    ├── log_strip.py                         # one-line tail / expandable
    ├── plan_screen.py                       # interview + approval overlay
    └── styles.tcss                          # Textual CSS

tests/
├── core/
│   ├── test_scenario_queue.py
│   ├── test_bug_store.py
│   ├── test_dedup.py
│   ├── test_event_bus.py
│   ├── test_browser_lock.py
│   └── test_run_paths.py
├── config/
│   ├── test_cli.py
│   └── test_project_yaml.py
├── runner/
│   ├── test_claude_proc.py                  # uses fake subprocess fixture
│   ├── test_event_log_tailer.py
│   └── fixtures/
│       └── stream_json_samples.jsonl
└── e2e/
    ├── smoke.sh                             # manual E2E (not in CI)
    ├── jira_mock.py                         # FastAPI mock
    └── fixtures/canned_page.html

pyproject.toml
.gitignore
```

### File responsibility boundaries

- `tui/*` reads `EventBus` + state snapshots only. Never spawns subprocesses, never calls Jira/MCP.
- `runner/*` writes to `EventBus` and stdout only. Never imports Textual.
- `core/*` is pure state — no I/O except `run_paths.py` which only does mkdir/path math.
- `config/*` does file I/O (yaml load/save, argparse) and no domain logic.
- Subprocess prompts are markdown files, never f-strings inlined into Python.

---

## Task 0: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `explorer/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Initialize uv project**

Run from `/home/chibionos/r/explorer`:

```bash
uv init --package --name explorer --python 3.11
```

Expected: `pyproject.toml`, `src/explorer/__init__.py` created.

- [ ] **Step 2: Rewrite `pyproject.toml`**

```toml
[project]
name = "explorer"
version = "0.1.0"
description = "Long-running TUI test explorer using Claude Code subprocesses"
requires-python = ">=3.11"
dependencies = [
    "textual>=0.85.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "fastapi>=0.110",
    "uvicorn>=0.27",
]

[project.scripts]
explorer = "explorer.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["explorer"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Flatten the package layout**

```bash
mv src/explorer ./explorer
rmdir src
```

- [ ] **Step 4: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.uv/
.pytest_cache/
.explorer/
*.egg-info/
dist/
build/
```

- [ ] **Step 5: Install deps**

Run: `uv sync --extra dev`
Expected: `.venv` created, all deps installed.

- [ ] **Step 6: Verify install**

Run: `uv run python -c "import textual, yaml; print('ok')"`
Expected output: `ok`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore explorer/__init__.py tests/__init__.py uv.lock
git commit -m "chore: scaffold uv project"
```

---

## Task 1: `core/dedup.py` — title signature

**Files:**
- Create: `explorer/core/__init__.py`, `explorer/core/dedup.py`
- Test: `tests/core/test_dedup.py`, `tests/core/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/core/__init__.py` (empty) and `tests/core/test_dedup.py`:

```python
from explorer.core.dedup import normalize_title, DedupIndex


def test_normalize_lowercases_and_strips_punctuation():
    assert normalize_title("Modal Close (X) misses 4px!") == "modal close x misses 4px"


def test_normalize_drops_stopwords():
    assert normalize_title("The save button on the page is broken") == "save button page broken"


def test_normalize_collapses_whitespace():
    assert normalize_title("  too    many   spaces  ") == "too many spaces"


def test_index_seeds_from_existing():
    idx = DedupIndex.from_pairs([("Save button broken", "ABC-1")])
    assert idx.lookup("Save Button Broken!") == "ABC-1"


def test_index_miss_returns_none():
    idx = DedupIndex.from_pairs([("Save button broken", "ABC-1")])
    assert idx.lookup("Totally different bug") is None


def test_index_record_updates():
    idx = DedupIndex.from_pairs([])
    idx.record("New bug found", "ABC-99")
    assert idx.lookup("new bug found") == "ABC-99"


def test_index_titles_for_prompt_returns_jira_pairs():
    idx = DedupIndex.from_pairs([("A bug", "ABC-1"), ("Another bug", "ABC-2")])
    pairs = idx.titles_for_prompt()
    assert ("ABC-1", "A bug") in pairs
    assert ("ABC-2", "Another bug") in pairs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_dedup.py -v`
Expected: ImportError (module doesn't exist).

- [ ] **Step 3: Implement `dedup.py`**

Create `explorer/core/__init__.py` (empty) and `explorer/core/dedup.py`:

```python
from __future__ import annotations
import re
from dataclasses import dataclass, field

_STOPWORDS = {"the", "a", "an", "on", "in", "to", "for", "with", "is", "are"}
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    s = _PUNCT_RE.sub(" ", title.lower())
    tokens = [t for t in _WS_RE.sub(" ", s).strip().split(" ") if t and t not in _STOPWORDS]
    return " ".join(tokens)


@dataclass
class DedupIndex:
    _by_sig: dict[str, str] = field(default_factory=dict)
    _by_key: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_pairs(cls, pairs: list[tuple[str, str]]) -> "DedupIndex":
        idx = cls()
        for title, key in pairs:
            idx.record(title, key)
        return idx

    def record(self, title: str, jira_key: str) -> None:
        self._by_sig[normalize_title(title)] = jira_key
        self._by_key[jira_key] = title

    def lookup(self, title: str) -> str | None:
        return self._by_sig.get(normalize_title(title))

    def titles_for_prompt(self) -> list[tuple[str, str]]:
        return [(k, t) for k, t in self._by_key.items()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_dedup.py -v`
Expected: all 7 pass.

- [ ] **Step 5: Commit**

```bash
git add explorer/core/__init__.py explorer/core/dedup.py tests/core/__init__.py tests/__init__.py tests/core/test_dedup.py
git commit -m "feat(core): add dedup index with normalized title signatures"
```

---

## Task 2: `core/scenario_queue.py`

**Files:**
- Create: `explorer/core/scenario_queue.py`
- Test: `tests/core/test_scenario_queue.py`

- [ ] **Step 1: Write failing tests**

```python
from explorer.core.scenario_queue import ScenarioQueue, Scenario, ScenarioStatus


def make(id: str, title: str = "t", goal: str = "g") -> Scenario:
    return Scenario(id=id, title=title, goal=goal)


def test_seed_with_scenarios():
    q = ScenarioQueue.from_scenarios([make("a"), make("b")])
    assert q.pending_count() == 2
    assert q.discovered_count() == 2
    assert q.done_count() == 0


def test_next_pops_in_order():
    q = ScenarioQueue.from_scenarios([make("a"), make("b")])
    s = q.next_pending()
    assert s.id == "a"


def test_next_pending_returns_none_when_empty():
    q = ScenarioQueue.from_scenarios([])
    assert q.next_pending() is None


def test_status_transitions():
    q = ScenarioQueue.from_scenarios([make("a")])
    s = q.next_pending()
    q.mark_running(s.id)
    assert q.status(s.id) == ScenarioStatus.RUNNING
    q.mark_done(s.id)
    assert q.status(s.id) == ScenarioStatus.DONE
    assert q.done_count() == 1


def test_mark_failed():
    q = ScenarioQueue.from_scenarios([make("a")])
    s = q.next_pending()
    q.mark_running(s.id)
    q.mark_failed(s.id, "boom")
    assert q.status(s.id) == ScenarioStatus.FAILED


def test_propose_adds_to_pending_and_increments_discovered():
    q = ScenarioQueue.from_scenarios([make("a")])
    q.propose(make("b", "new"))
    assert q.pending_count() == 2
    assert q.discovered_count() == 2


def test_propose_dedups_by_id():
    q = ScenarioQueue.from_scenarios([make("a")])
    q.propose(make("a", "dup"))
    assert q.pending_count() == 1
    assert q.discovered_count() == 1


def test_all_done_when_no_pending_or_running():
    q = ScenarioQueue.from_scenarios([make("a")])
    assert not q.all_done()
    s = q.next_pending()
    q.mark_running(s.id)
    assert not q.all_done()
    q.mark_done(s.id)
    assert q.all_done()


def test_requeue_failed():
    q = ScenarioQueue.from_scenarios([make("a")])
    s = q.next_pending()
    q.mark_running(s.id)
    q.mark_failed(s.id, "boom")
    q.requeue(s.id)
    assert q.status(s.id) == ScenarioStatus.PENDING
```

- [ ] **Step 2: Verify fails**

Run: `uv run pytest tests/core/test_scenario_queue.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from collections import OrderedDict


class ScenarioStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Scenario:
    id: str
    title: str
    goal: str
    parent_id: str | None = None
    error: str | None = None


@dataclass
class ScenarioQueue:
    _scenarios: OrderedDict[str, Scenario] = field(default_factory=OrderedDict)
    _status: dict[str, ScenarioStatus] = field(default_factory=dict)

    @classmethod
    def from_scenarios(cls, scenarios: list[Scenario]) -> "ScenarioQueue":
        q = cls()
        for s in scenarios:
            q._scenarios[s.id] = s
            q._status[s.id] = ScenarioStatus.PENDING
        return q

    def propose(self, scenario: Scenario) -> bool:
        if scenario.id in self._scenarios:
            return False
        self._scenarios[scenario.id] = scenario
        self._status[scenario.id] = ScenarioStatus.PENDING
        return True

    def next_pending(self) -> Scenario | None:
        for sid, st in self._status.items():
            if st == ScenarioStatus.PENDING:
                return self._scenarios[sid]
        return None

    def status(self, sid: str) -> ScenarioStatus:
        return self._status[sid]

    def mark_running(self, sid: str) -> None:
        self._status[sid] = ScenarioStatus.RUNNING

    def mark_done(self, sid: str) -> None:
        self._status[sid] = ScenarioStatus.DONE

    def mark_failed(self, sid: str, error: str) -> None:
        self._status[sid] = ScenarioStatus.FAILED
        self._scenarios[sid].error = error

    def requeue(self, sid: str) -> None:
        self._status[sid] = ScenarioStatus.PENDING
        self._scenarios[sid].error = None

    def pending_count(self) -> int:
        return sum(1 for st in self._status.values() if st == ScenarioStatus.PENDING)

    def done_count(self) -> int:
        return sum(1 for st in self._status.values() if st == ScenarioStatus.DONE)

    def discovered_count(self) -> int:
        return len(self._scenarios)

    def all_done(self) -> bool:
        return all(st in (ScenarioStatus.DONE, ScenarioStatus.FAILED) for st in self._status.values())

    def scenarios(self) -> list[Scenario]:
        return list(self._scenarios.values())
```

- [ ] **Step 4: Verify pass**

Run: `uv run pytest tests/core/test_scenario_queue.py -v`
Expected: 9 pass.

- [ ] **Step 5: Commit**

```bash
git add explorer/core/scenario_queue.py tests/core/test_scenario_queue.py
git commit -m "feat(core): add scenario queue"
```

---

## Task 3: `core/bug_store.py`

**Files:**
- Create: `explorer/core/bug_store.py`
- Test: `tests/core/test_bug_store.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Verify fails**

Run: `uv run pytest tests/core/test_bug_store.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Bug:
    uuid: str
    jira_key: str
    title: str
    scenario_id: str
    screenshot_path: str
    jira_url: str


class BugStore:
    def __init__(self, mirror_path: Path) -> None:
        self._mirror = mirror_path
        self._mirror.parent.mkdir(parents=True, exist_ok=True)
        self._bugs: list[Bug] = []

    def add(self, bug: Bug) -> None:
        self._bugs.append(bug)
        self._persist()

    def count(self) -> int:
        return len(self._bugs)

    def list_newest_first(self) -> list[Bug]:
        return list(reversed(self._bugs))

    def _persist(self) -> None:
        self._mirror.write_text(json.dumps([asdict(b) for b in self._bugs], indent=2))
```

- [ ] **Step 4: Verify pass**

Run: `uv run pytest tests/core/test_bug_store.py -v`
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add explorer/core/bug_store.py tests/core/test_bug_store.py
git commit -m "feat(core): add bug store with disk mirror"
```

---

## Task 4: `core/event_bus.py`

**Files:**
- Create: `explorer/core/event_bus.py`
- Test: `tests/core/test_event_bus.py`

- [ ] **Step 1: Write failing tests**

```python
import asyncio
from explorer.core.event_bus import EventBus, Event


async def test_subscribe_receives_published():
    bus = EventBus()
    received = []

    async def consume():
        async for ev in bus.subscribe("bug_filed"):
            received.append(ev)
            if len(received) == 2:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    await bus.publish(Event(type="bug_filed", data={"k": "ABC-1"}))
    await bus.publish(Event(type="bug_filed", data={"k": "ABC-2"}))
    await asyncio.wait_for(task, timeout=1)
    assert [e.data["k"] for e in received] == ["ABC-1", "ABC-2"]


async def test_wildcard_subscription_receives_all():
    bus = EventBus()
    received = []

    async def consume():
        async for ev in bus.subscribe("*"):
            received.append(ev.type)
            if len(received) == 3:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    await bus.publish(Event(type="a", data={}))
    await bus.publish(Event(type="b", data={}))
    await bus.publish(Event(type="c", data={}))
    await asyncio.wait_for(task, timeout=1)
    assert received == ["a", "b", "c"]


async def test_unrelated_subscriber_does_not_receive():
    bus = EventBus()
    received = []

    async def consume():
        async for ev in bus.subscribe("scenario_done"):
            received.append(ev)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    await bus.publish(Event(type="bug_filed", data={}))
    await asyncio.sleep(0.05)
    assert received == []
    task.cancel()
```

- [ ] **Step 2: Verify fails**

Run: `uv run pytest tests/core/test_event_bus.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[tuple[str, asyncio.Queue[Event]]] = []

    async def publish(self, event: Event) -> None:
        for type_filter, queue in self._subscribers:
            if type_filter == "*" or type_filter == event.type:
                await queue.put(event)

    async def subscribe(self, type_filter: str) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        entry = (type_filter, queue)
        self._subscribers.append(entry)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.remove(entry)
```

- [ ] **Step 4: Verify pass**

Run: `uv run pytest tests/core/test_event_bus.py -v`
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add explorer/core/event_bus.py tests/core/test_event_bus.py
git commit -m "feat(core): add asyncio event bus"
```

---

## Task 5: `core/browser_lock.py`

**Files:**
- Create: `explorer/core/browser_lock.py`
- Test: `tests/core/test_browser_lock.py`

- [ ] **Step 1: Write failing tests**

```python
import asyncio
from explorer.core.browser_lock import BrowserLock


async def test_lock_serializes_sections():
    lock = BrowserLock()
    log = []

    async def section(name, hold):
        async with lock.acquire():
            log.append(f"start-{name}")
            await asyncio.sleep(hold)
            log.append(f"end-{name}")

    await asyncio.gather(section("a", 0.05), section("b", 0.01))
    assert log == ["start-a", "end-a", "start-b", "end-b"]
```

- [ ] **Step 2: Verify fails**

Run: `uv run pytest tests/core/test_browser_lock.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager


class BrowserLock:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self):
        await self._lock.acquire()
        try:
            yield
        finally:
            self._lock.release()
```

- [ ] **Step 4: Verify pass**

Run: `uv run pytest tests/core/test_browser_lock.py -v`
Expected: 1 pass.

- [ ] **Step 5: Commit**

```bash
git add explorer/core/browser_lock.py tests/core/test_browser_lock.py
git commit -m "feat(core): add browser lock"
```

---

## Task 6: `core/run_paths.py`

**Files:**
- Create: `explorer/core/run_paths.py`
- Test: `tests/core/test_run_paths.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Verify fails**

Run: `uv run pytest tests/core/test_run_paths.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class RunPaths:
    root: Path

    @classmethod
    def new(cls, base: Path) -> "RunPaths":
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        root = base / "runs" / stamp
        root.mkdir(parents=True, exist_ok=True)
        (root / "screenshots").mkdir(exist_ok=True)
        return cls(root=root)

    @property
    def screenshots_dir(self) -> Path:
        return self.root / "screenshots"

    @property
    def plan_yaml(self) -> Path:
        return self.root / "plan.yaml"

    @property
    def events_log(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def bugs_json(self) -> Path:
        return self.root / "bugs.json"

    @property
    def event_log_for_subprocess(self) -> Path:
        return self.root / "explorer_event_log.jsonl"
```

- [ ] **Step 4: Verify pass**

Run: `uv run pytest tests/core/test_run_paths.py -v`
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add explorer/core/run_paths.py tests/core/test_run_paths.py
git commit -m "feat(core): add per-run path layout"
```

---

## Task 7: `config/project_yaml.py`

**Files:**
- Create: `explorer/config/__init__.py`, `explorer/config/project_yaml.py`
- Test: `tests/config/__init__.py`, `tests/config/test_project_yaml.py`

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path
from explorer.config.project_yaml import ProjectConfig, load, save


def test_save_then_load_roundtrip(tmp_path: Path):
    cfg = ProjectConfig(jira_project="ABC", epic_key="ABC-1042",
                        codebase_path=str(tmp_path / "code"),
                        tab_url="https://app.example.com", bu_name=None)
    save(cfg, tmp_path / ".explorer/project.yaml")
    loaded = load(tmp_path / ".explorer/project.yaml")
    assert loaded == cfg


def test_load_missing_returns_none(tmp_path: Path):
    assert load(tmp_path / "nope.yaml") is None


def test_merge_overrides_keeps_existing(tmp_path: Path):
    cfg = ProjectConfig(jira_project="ABC", epic_key="ABC-1", codebase_path="/c",
                        tab_url="u", bu_name=None)
    merged = cfg.merge(jira_project=None, epic_key="ABC-2", codebase_path=None,
                       tab_url=None, bu_name="work")
    assert merged.jira_project == "ABC"
    assert merged.epic_key == "ABC-2"
    assert merged.bu_name == "work"
```

- [ ] **Step 2: Verify fails**

Run: `uv run pytest tests/config/test_project_yaml.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Verify pass**

Run: `uv run pytest tests/config/test_project_yaml.py -v`
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add explorer/config/__init__.py explorer/config/project_yaml.py tests/config/__init__.py tests/config/test_project_yaml.py
git commit -m "feat(config): add project.yaml load/save"
```

---

## Task 8: `config/cli.py`

**Files:**
- Create: `explorer/config/cli.py`
- Test: `tests/config/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path
import pytest
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


def test_resolve_uses_disk_when_flags_omitted(tmp_path: Path):
    disk_cfg = ProjectConfig(jira_project="ABC", epic_key="ABC-1", codebase_path="/c",
                             tab_url="u", bu_name=None)
    save(disk_cfg, tmp_path / ".explorer/project.yaml")
    args = parse_args([])
    cfg = resolve_config(args, project_dir=tmp_path)
    assert cfg == disk_cfg


def test_resolve_first_run_requires_all_flags(tmp_path: Path):
    args = parse_args(["--jira-project", "ABC"])
    with pytest.raises(SystemExit):
        resolve_config(args, project_dir=tmp_path)


def test_resolve_flags_override_disk(tmp_path: Path):
    save(ProjectConfig(jira_project="ABC", epic_key="ABC-1", codebase_path="/c",
                       tab_url="u", bu_name=None),
         tmp_path / ".explorer/project.yaml")
    args = parse_args(["--epic", "ABC-2"])
    cfg = resolve_config(args, project_dir=tmp_path)
    assert cfg.epic_key == "ABC-2"
    assert cfg.jira_project == "ABC"
```

- [ ] **Step 2: Verify fails**

Run: `uv run pytest tests/config/test_cli.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Verify pass**

Run: `uv run pytest tests/config/test_cli.py -v`
Expected: 4 pass.

- [ ] **Step 5: Commit**

```bash
git add explorer/config/cli.py tests/config/test_cli.py
git commit -m "feat(config): add CLI parser + resolve"
```

---

## Task 9: `runner/event_log_tailer.py`

**Files:**
- Create: `explorer/runner/__init__.py`, `explorer/runner/event_log_tailer.py`
- Test: `tests/runner/__init__.py`, `tests/runner/test_event_log_tailer.py`

- [ ] **Step 1: Write failing tests**

```python
import asyncio
import json
from pathlib import Path
from explorer.core.event_bus import EventBus
from explorer.runner.event_log_tailer import tail_event_log


async def test_emits_parsed_events(tmp_path: Path):
    log = tmp_path / "ev.jsonl"
    log.touch()
    bus = EventBus()
    received = []

    async def consume():
        async for ev in bus.subscribe("*"):
            received.append(ev)
            if len(received) == 2:
                return

    tailer = asyncio.create_task(tail_event_log(log, bus, poll_interval=0.01))
    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.02)
    log.write_text(json.dumps({"type": "bug_observed", "data": {"uuid": "u1"}}) + "\n")
    await asyncio.sleep(0.03)
    with log.open("a") as f:
        f.write(json.dumps({"type": "scenario_proposed", "data": {"title": "x"}}) + "\n")
    await asyncio.wait_for(consumer, timeout=1)
    tailer.cancel()
    types = [e.type for e in received]
    assert "bug_observed" in types
    assert "scenario_proposed" in types


async def test_skips_malformed_lines(tmp_path: Path):
    log = tmp_path / "ev.jsonl"
    log.write_text("not json\n" + json.dumps({"type": "note", "data": {"text": "ok"}}) + "\n")
    bus = EventBus()
    received = []

    async def consume():
        async for ev in bus.subscribe("*"):
            received.append(ev)
            if len(received) == 2:
                return

    tailer = asyncio.create_task(tail_event_log(log, bus, poll_interval=0.01))
    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(consumer, timeout=1)
    tailer.cancel()
    types = [e.type for e in received]
    assert "parse_error" in types
    assert "note" in types
```

- [ ] **Step 2: Verify fails**

Run: `uv run pytest tests/runner/test_event_log_tailer.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from ..core.event_bus import EventBus, Event


async def tail_event_log(path: Path, bus: EventBus, *, poll_interval: float = 0.1) -> None:
    path.touch()
    pos = 0
    while True:
        with path.open() as f:
            f.seek(pos)
            for line in f:
                if not line.endswith("\n"):
                    break
                pos += len(line.encode())
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    await bus.publish(Event(type=rec["type"], data=rec.get("data", {})))
                except (json.JSONDecodeError, KeyError) as e:
                    await bus.publish(Event(type="parse_error", data={"line": line, "error": str(e)}))
        await asyncio.sleep(poll_interval)
```

- [ ] **Step 4: Verify pass**

Run: `uv run pytest tests/runner/test_event_log_tailer.py -v`
Expected: 2 pass.

- [ ] **Step 5: Commit**

```bash
git add explorer/runner/__init__.py explorer/runner/event_log_tailer.py tests/runner/__init__.py tests/runner/test_event_log_tailer.py
git commit -m "feat(runner): add JSONL event log tailer"
```

---

## Task 10: `runner/claude_proc.py` — spawn claude + parse stream-json

This is the trickiest module. It must:
- Spawn a `claude` subprocess via the asyncio subprocess API (the argv form, not shell).
- Parse each line of stdout as JSON.
- Emit `subagent_start` / `subagent_end` whenever the parent uses the `Task` tool.
- Emit `note` for assistant text deltas (truncated for log strip).
- Emit `process_exit` when the subprocess ends.

The implementation imports the asyncio subprocess spawn function under a local alias `_spawn_claude` to keep the call site readable. The function name is mechanical; what matters is the argv form (a list of strings, not a shell command).

**Files:**
- Create: `explorer/runner/claude_proc.py`
- Test: `tests/runner/test_claude_proc.py`
- Create fixture: `tests/runner/fixtures/stream_json_samples.jsonl`

- [ ] **Step 1: Write the fixture**

Create `tests/runner/fixtures/stream_json_samples.jsonl` (realistic shape of Claude Code stream-json — verify against `claude --output-format stream-json -p` actual output in Step 6):

```json
{"type": "system", "subtype": "init", "session_id": "s1"}
{"type": "assistant", "message": {"content": [{"type": "text", "text": "Looking at the page..."}]}}
{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "tu_1", "name": "Task", "input": {"description": "File bug", "subagent_type": "general-purpose", "prompt": "..."}}]}}
{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "Filed ABC-1051"}]}}
{"type": "result", "subtype": "success", "session_id": "s1"}
```

- [ ] **Step 2: Write failing tests**

```python
import json
from explorer.runner.claude_proc import parse_stream_line


def test_parse_assistant_text_emits_note():
    line = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Looking..."}]}})
    events = parse_stream_line(line, session_label="explorer-1")
    assert any(e.type == "note" for e in events)


def test_parse_task_tool_use_emits_subagent_start():
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "tu_1", "name": "Task",
         "input": {"description": "File bug", "subagent_type": "general-purpose"}}
    ]}})
    events = parse_stream_line(line, session_label="explorer-1")
    starts = [e for e in events if e.type == "subagent_start"]
    assert len(starts) == 1
    assert starts[0].data["tool_use_id"] == "tu_1"
    assert starts[0].data["description"] == "File bug"


def test_parse_tool_result_emits_subagent_end():
    line = json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "tu_1", "content": "done"}
    ]}})
    events = parse_stream_line(line, session_label="explorer-1")
    ends = [e for e in events if e.type == "subagent_end"]
    assert len(ends) == 1


def test_parse_non_task_tool_use_ignored():
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "tu_2", "name": "Bash", "input": {"command": "ls"}}
    ]}})
    events = parse_stream_line(line, session_label="explorer-1")
    assert not any(e.type == "subagent_start" for e in events)


def test_parse_malformed_returns_empty():
    events = parse_stream_line("not json", session_label="x")
    assert events == []
```

- [ ] **Step 3: Verify fails**

Run: `uv run pytest tests/runner/test_claude_proc.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `parse_stream_line` and `run_claude`**

```python
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from typing import Mapping
from ..core.event_bus import EventBus, Event

# Alias for readability; spawns a subprocess from an argv list (no shell).
_spawn = asyncio.create_subprocess_exec


def parse_stream_line(line: str, *, session_label: str) -> list[Event]:
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return []

    events: list[Event] = []
    if rec.get("type") == "assistant":
        for block in rec.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text"):
                text = block["text"].strip()
                if text:
                    events.append(Event(type="note", data={
                        "session_label": session_label,
                        "text": text[:200],
                    }))
            elif block.get("type") == "tool_use" and block.get("name") == "Task":
                events.append(Event(type="subagent_start", data={
                    "session_label": session_label,
                    "tool_use_id": block.get("id", ""),
                    "description": block.get("input", {}).get("description", ""),
                    "subagent_type": block.get("input", {}).get("subagent_type", ""),
                }))
    elif rec.get("type") == "user":
        for block in rec.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                events.append(Event(type="subagent_end", data={
                    "session_label": session_label,
                    "tool_use_id": block.get("tool_use_id", ""),
                }))
    return events


async def run_claude(
    *, prompt: str, cwd: Path, env_overrides: Mapping[str, str],
    bus: EventBus, session_label: str,
) -> int:
    env = os.environ.copy()
    env.update(env_overrides)
    proc = await _spawn(
        "claude", "--output-format", "stream-json",
        "--include-partial-messages",
        "--dangerously-skip-permissions",
        "-p", prompt,
        cwd=str(cwd), env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await bus.publish(Event(type="process_start",
                            data={"session_label": session_label, "pid": proc.pid}))
    assert proc.stdout is not None
    async for raw in proc.stdout:
        for ev in parse_stream_line(raw.decode("utf-8", errors="replace"),
                                    session_label=session_label):
            await bus.publish(ev)
    rc = await proc.wait()
    await bus.publish(Event(type="process_exit",
                            data={"session_label": session_label, "returncode": rc}))
    return rc
```

- [ ] **Step 5: Verify parse tests pass**

Run: `uv run pytest tests/runner/test_claude_proc.py -v`
Expected: 5 pass.

- [ ] **Step 6: Validate stream-json shape against real `claude`**

Run interactively, ONE TIME, to confirm field names:

```bash
echo "say hi" | claude --output-format stream-json --include-partial-messages -p 2>/dev/null | head -20
```

Confirm that:
- assistant text blocks have shape `{"type":"assistant","message":{"content":[{"type":"text","text":...}]}}`
- Task tool uses have shape `{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Task","id":...,"input":{"description":..., "subagent_type":...}}]}}`
- Tool results come back as `{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":..., "content":...}]}}`

If field names differ, **update both the fixture and `parse_stream_line` to match reality before continuing.** This is the single biggest assumption in the design; getting it wrong cascades.

- [ ] **Step 7: Commit**

```bash
git add explorer/runner/claude_proc.py tests/runner/test_claude_proc.py tests/runner/fixtures/stream_json_samples.jsonl
git commit -m "feat(runner): spawn claude subprocess + parse stream-json"
```

---

## Task 11: Subprocess prompts (markdown)

Prompts define the actual behavior of every Claude subprocess. They live as markdown so they can be edited without code changes. Each prompt MUST instruct the subprocess to write structured JSON lines to `$EXPLORER_EVENT_LOG`.

**Files:**
- Create: `explorer/runner/prompts/__init__.py` (empty)
- Create: `explorer/runner/prompts/system_planner.md`
- Create: `explorer/runner/prompts/system_explorer.md`
- Create: `explorer/runner/prompts/system_bug_filer.md`
- Create: `explorer/runner/prompts/system_proposer.md`

- [ ] **Step 1: Write `system_planner.md`**

```markdown
# Planner

You are a test-plan author. Your job is to interview the user about what they
want to test in their web app, then output a list of exploratory test scenarios.

## Interview style

Ask 3-5 questions, ONE AT A TIME. Each question should be short. Focus on:
1. What flows / pages / features are highest-priority to explore?
2. Are there known-weak areas, recent changes, or specific user complaints?
3. What user personas / device contexts (mobile / desktop / RTL / a11y) should we cover?
4. Any flows to AVOID (paid actions, destructive ops, prod data)?
5. Approximate depth: smoke (5–10 scenarios) or thorough (20+)?

You read user answers from stdin (the orchestrator pipes them).

## Output

When done, append the plan to `$EXPLORER_EVENT_LOG` as a single JSON line:

`{"type": "plan_ready", "data": {"scenarios": [{"id": "s1", "title": "...", "goal": "..."}, ...]}}`

Each scenario has:
- `id` — short kebab slug, unique
- `title` — one-line human description
- `goal` — what we're trying to discover (1-2 sentences); the explorer reads this

DO NOT file bugs. DO NOT touch the browser. Output the plan, then exit.
```

- [ ] **Step 2: Write `system_explorer.md`**

```markdown
# Explorer

You are an exploratory tester. You have ONE scenario to run against a real web
browser tab that the user has open.

## Scenario

`{{SCENARIO_TITLE}}`

Goal: `{{SCENARIO_GOAL}}`

## Environment

- The browser is driven via the `browser-harness` CLI, invoked from Bash.
  Recipe: `browser-harness -c 'capture_screenshot()'`,
  `browser-harness -c 'click_at_xy(x, y)'`, etc. See `~/.claude/CLAUDE.md` for
  full semantics. Do not launch a new browser. Do not open new tabs.
- Your working directory IS the product codebase. You can `Read`/`Grep`/`Glob`
  it, but only AFTER you've observed a bug — exploration comes first.
- Jira project: `{{JIRA_PROJECT}}`. Bug epic: `{{EPIC_KEY}}`.
- Already-filed bug titles (for dedup hints): `{{KNOWN_BUG_TITLES}}`

## What to do

1. Verify the tab is on the right page:
   `browser-harness -c 'print(page_info())'`. If wrong, append a `note` event
   to `$EXPLORER_EVENT_LOG` and exit.
2. Start the scenario by appending to `$EXPLORER_EVENT_LOG`:
   `{"type": "scenario_start", "data": {"scenario_id": "{{SCENARIO_ID}}", "title": "{{SCENARIO_TITLE}}"}}`
3. Explore. Take screenshots. Click around. Try edge cases relevant to the
   goal (empty states, long inputs, rapid interactions, refresh mid-flow).
4. When you observe what looks like a bug:
   - Save a screenshot to `$SCREENSHOTS_DIR/<uuid>.png` (generate the uuid
     with `python -c "import uuid;print(uuid.uuid4())"`).
   - Append a `bug_observed` event with uuid, scenario_id, title, symptom,
     page_url, screenshot_path.
   - Use the `Task` tool to dispatch a `general-purpose` sub-agent with the
     bug-filer prompt at `$BUG_FILER_PROMPT_PATH`. Read that file and use its
     contents as the sub-agent's prompt, substituting `{{BUG_UUID}}`,
     `{{SCREENSHOT_PATH}}`, `{{BUG_TITLE}}`, `{{BUG_SYMPTOM}}`,
     `{{PAGE_URL}}`. Run in background.
   - Continue exploring without waiting.
5. If you discover a flow worth its own scenario, dispatch a `Task` sub-agent
   with the proposer prompt at `$PROPOSER_PROMPT_PATH`.
6. When you've spent meaningful effort (3-10 minutes or you've exhausted
   obvious paths), append `scenario_done` and exit. In-flight Task
   sub-agents will finish before exit.

## Bug filing thresholds

File a bug if you notice:
- Anything broken: 404, 500, JS error, blank page, button doesn't do what its label says.
- Anything misleading: states that contradict reality, labels that lie.
- Anything sloppy: misaligned elements, overflow, contrast issues, untranslated strings.
- Anything counter-intuitive: required fields without asterisks, success toasts that vanish in 200ms, modals you can't dismiss with Escape.

Do NOT file: cosmetic preferences, suggestions to add features.

## Important

- Cap each bug observation: dispatch the bug-filer Task and move on.
- The bug-filer dedups, so duplicates are OK to attempt.
- Stay within the scenario goal. New ideas → propose a scenario.
```

- [ ] **Step 3: Write `system_bug_filer.md`**

```markdown
# Bug Filer

A sibling explorer agent observed a possible bug. Confirm it's real, find the
responsible code, file (or comment on) a Jira issue under the Bug Explorer
epic, and emit a result event.

## Bug details

- UUID: `{{BUG_UUID}}`
- Title: `{{BUG_TITLE}}`
- Symptom: `{{BUG_SYMPTOM}}`
- Page URL: `{{PAGE_URL}}`
- Screenshot: `{{SCREENSHOT_PATH}}`
- Jira project: `{{JIRA_PROJECT}}`
- Epic: `{{EPIC_KEY}}`
- Already-filed titles: `{{KNOWN_BUG_TITLES}}`

## Steps

1. **Dedup check.** If any existing title in `{{KNOWN_BUG_TITLES}}` describes
   essentially the same bug, you'll add a comment instead (proceed to step 4).

2. **Code search.** Working directory is the product codebase. Search for code
   producing this UI. Use `Grep`/`Read`/`Glob` on filenames and visible strings.
   Identify:
   - The most likely source file(s) and line ranges.
   - A plausible reason it's broken.
   - A suggested fix outline (specific enough for another coding agent to act
     on without re-investigating).

3. **File issue.** Use `mcp__atlassian__createJiraIssue`. Project =
   `{{JIRA_PROJECT}}`. Type = `Bug`. Parent epic = `{{EPIC_KEY}}`. Title = a
   short, descriptive headline. Body must include:
   - **Symptom**: one paragraph.
   - **Steps to reproduce**: page URL + interaction sequence.
   - **Screenshot**: attach via Atlassian MCP, or note the filesystem path.
   - **Suspected code**: file:line ranges + 5-10 line snippet.
   - **Suggested fix**: 3-6 sentences with exact identifiers.
   - **Labels**: `bug-explorer` + relevant area tags.

4. **Or comment on existing.** If deduped: `mcp__atlassian__addCommentToJiraIssue`
   to the matched key with a fresh repro + screenshot + suggested-fix delta.

5. **Emit result** by appending one JSON line to `$EXPLORER_EVENT_LOG`:

   - New issue: `{"type": "bug_filed", "data": {"uuid": "...", "jira_key": "...", "jira_url": "...", "title": "..."}}`
   - Duplicate comment: `{"type": "bug_dup_comment", "data": {"uuid": "...", "existing_key": "...", "comment_url": "..."}}`
   - Failure: `{"type": "bug_filed_failed", "data": {"uuid": "...", "error": "...", "prepared_body": "..."}}`

Do not touch the browser. Do not run new scenarios.
```

- [ ] **Step 4: Write `system_proposer.md`**

```markdown
# Scenario Proposer

You were dispatched by an explorer that noticed an interesting area worth its
own scenario.

## Input

- Current scenario id: `{{PARENT_SCENARIO_ID}}`
- Observation: `{{OBSERVATION}}` (free text from the explorer)

## What to do

Propose 1-3 new scenarios. Each is a focused exploration goal. Append to
`$EXPLORER_EVENT_LOG`, one line per proposal:

`{"type": "scenario_proposed", "data": {"id": "<kebab-slug>", "title": "...", "goal": "...", "parent_scenario_id": "{{PARENT_SCENARIO_ID}}"}}`

Use short kebab-case ids. Do not file bugs. Do not touch the browser. Exit.
```

- [ ] **Step 5: Commit**

```bash
git add explorer/runner/prompts/__init__.py explorer/runner/prompts/*.md
git commit -m "feat(runner): add subprocess prompts"
```

---

## Task 12: `runner/planner.py` and `runner/explorer.py` drivers

These are thin orchestrators over `run_claude`. No new logic.

**Files:**
- Create: `explorer/runner/planner.py`
- Create: `explorer/runner/explorer.py`

- [ ] **Step 1: Implement `planner.py`**

```python
from __future__ import annotations
from pathlib import Path
from ..core.event_bus import EventBus
from .claude_proc import run_claude


PROMPTS_DIR = Path(__file__).parent / "prompts"


async def run_planner(*, event_log: Path, bus: EventBus, codebase_path: Path) -> int:
    prompt = (PROMPTS_DIR / "system_planner.md").read_text()
    env = {"EXPLORER_EVENT_LOG": str(event_log)}
    return await run_claude(prompt=prompt, cwd=codebase_path,
                            env_overrides=env, bus=bus, session_label="planner")
```

(The interactive variant that pipes stdin lives in `runner/interview.py`, Task 13.)

- [ ] **Step 2: Implement `explorer.py`**

```python
from __future__ import annotations
from pathlib import Path
from ..core.event_bus import EventBus
from ..core.dedup import DedupIndex
from ..core.scenario_queue import Scenario
from .claude_proc import run_claude


PROMPTS_DIR = Path(__file__).parent / "prompts"


def _substitute(template: str, vars: dict[str, str]) -> str:
    out = template
    for k, v in vars.items():
        out = out.replace("{{" + k + "}}", v)
    return out


async def run_explorer(
    *, scenario: Scenario, codebase_path: Path, event_log: Path,
    screenshots_dir: Path, jira_project: str, epic_key: str,
    dedup: DedupIndex, bus: EventBus, session_label: str,
    bu_name: str | None = None,
) -> int:
    template = (PROMPTS_DIR / "system_explorer.md").read_text()
    known = "; ".join(f"{k}: {t}" for k, t in dedup.titles_for_prompt()) or "(none yet)"
    prompt = _substitute(template, {
        "SCENARIO_ID": scenario.id,
        "SCENARIO_TITLE": scenario.title,
        "SCENARIO_GOAL": scenario.goal,
        "JIRA_PROJECT": jira_project,
        "EPIC_KEY": epic_key,
        "KNOWN_BUG_TITLES": known,
    })
    env = {
        "EXPLORER_EVENT_LOG": str(event_log),
        "SCREENSHOTS_DIR": str(screenshots_dir),
        "BUG_FILER_PROMPT_PATH": str(PROMPTS_DIR / "system_bug_filer.md"),
        "PROPOSER_PROMPT_PATH": str(PROMPTS_DIR / "system_proposer.md"),
        "JIRA_PROJECT": jira_project,
        "EPIC_KEY": epic_key,
    }
    if bu_name:
        env["BU_NAME"] = bu_name
    return await run_claude(prompt=prompt, cwd=codebase_path,
                            env_overrides=env, bus=bus, session_label=session_label)
```

- [ ] **Step 3: Commit**

```bash
git add explorer/runner/planner.py explorer/runner/explorer.py
git commit -m "feat(runner): add planner and explorer subprocess drivers"
```

---

## Task 13: `runner/interview.py` — interactive variant (stdin pipe)

**Files:**
- Create: `explorer/runner/interview.py`

- [ ] **Step 1: Implement**

```python
from __future__ import annotations
import asyncio
import os
from pathlib import Path
from ..core.event_bus import EventBus, Event
from .claude_proc import parse_stream_line, _spawn


async def run_interactive_claude(
    *, prompt: str, cwd: Path, env_overrides: dict[str, str],
    bus: EventBus, session_label: str, answers: asyncio.Queue[str],
) -> int:
    env = os.environ.copy()
    env.update(env_overrides)
    proc = await _spawn(
        "claude", "--output-format", "stream-json",
        "--include-partial-messages",
        "--dangerously-skip-permissions",
        "-p", prompt,
        cwd=str(cwd), env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await bus.publish(Event(type="process_start",
                            data={"session_label": session_label, "pid": proc.pid}))

    async def pump_stdin():
        assert proc.stdin is not None
        try:
            while True:
                line = await answers.get()
                proc.stdin.write(line.encode("utf-8") + b"\n")
                await proc.stdin.drain()
        except asyncio.CancelledError:
            pass

    stdin_task = asyncio.create_task(pump_stdin())
    try:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            for ev in parse_stream_line(raw.decode("utf-8", errors="replace"),
                                        session_label=session_label):
                await bus.publish(ev)
        return await proc.wait()
    finally:
        stdin_task.cancel()
        await bus.publish(Event(type="process_exit",
                                data={"session_label": session_label,
                                      "returncode": proc.returncode or -1}))
```

- [ ] **Step 2: Commit**

```bash
git add explorer/runner/interview.py
git commit -m "feat(runner): add interactive claude driver (stdin from user)"
```

---

## Task 14: TUI skeleton — `tui/app.py`, header, log strip, styles

**Files:**
- Create: `explorer/tui/__init__.py` (empty)
- Create: `explorer/tui/app.py`
- Create: `explorer/tui/header.py`
- Create: `explorer/tui/log_strip.py`
- Create: `explorer/tui/styles.tcss`

- [ ] **Step 1: Write `tui/styles.tcss`**

```css
Screen { background: $surface; }
#header { height: 1; background: $primary; color: $text; padding: 0 1; }
#sessions { width: 50%; border-right: solid $accent; }
#bugs { width: 50%; }
#log { dock: bottom; height: 1; background: $surface-darken-1; color: $text-muted; padding: 0 1; }
#log.expanded { height: 10; }
```

- [ ] **Step 2: Write `tui/header.py`**

```python
from __future__ import annotations
from textual.reactive import reactive
from textual.widget import Widget


class Header(Widget):
    bug_count: reactive[int] = reactive(0)
    pending: reactive[int] = reactive(0)
    discovered: reactive[int] = reactive(0)
    jira_project: reactive[str] = reactive("?")
    epic_key: reactive[str] = reactive("?")
    codebase_path: reactive[str] = reactive("?")

    def render(self) -> str:
        return (
            f"explorer ─ Bugs: {self.bug_count} │ Pending: {self.pending} │ "
            f"Discovered: {self.discovered} │ Jira: {self.jira_project} / "
            f"Epic {self.epic_key} │ Code: {self.codebase_path}"
        )
```

- [ ] **Step 3: Write `tui/log_strip.py`**

```python
from __future__ import annotations
from collections import deque
from textual.reactive import reactive
from textual.widget import Widget


class LogStrip(Widget):
    expanded: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self._lines: deque[str] = deque(maxlen=10)

    def append(self, line: str) -> None:
        self._lines.append(line)
        self.refresh()

    def toggle(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.add_class("expanded")
        else:
            self.remove_class("expanded")

    def render(self) -> str:
        if not self._lines:
            return "(idle)"
        if not self.expanded:
            return self._lines[-1]
        return "\n".join(self._lines)
```

- [ ] **Step 4: Write minimal `tui/app.py`**

```python
from __future__ import annotations
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Placeholder

from ..core.event_bus import EventBus
from ..core.bug_store import BugStore
from ..core.scenario_queue import ScenarioQueue
from ..core.run_paths import RunPaths
from ..config.project_yaml import ProjectConfig
from .header import Header
from .log_strip import LogStrip


class ExplorerApp(App):
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        ("q", "quit", "quit"),
        ("e", "toggle_log", "expand log"),
    ]

    def __init__(self, *, cfg: ProjectConfig, bus: EventBus, queue: ScenarioQueue,
                 bugs: BugStore, run_paths: RunPaths) -> None:
        super().__init__()
        self._cfg = cfg
        self._bus = bus
        self._queue = queue
        self._bugs = bugs
        self._run_paths = run_paths

    def compose(self) -> ComposeResult:
        self.header = Header(id="header")
        self.header.jira_project = self._cfg.jira_project
        self.header.epic_key = self._cfg.epic_key
        self.header.codebase_path = self._cfg.codebase_path
        yield self.header
        with Horizontal():
            yield Placeholder(name="SESSIONS", id="sessions")
            yield Placeholder(name="BUGS", id="bugs")
        self.log_strip = LogStrip()
        self.log_strip.id = "log"
        yield self.log_strip

    def action_toggle_log(self) -> None:
        self.log_strip.toggle()
```

- [ ] **Step 5: Smoke-run the skeleton**

Add a temporary `tui_smoke.py` at repo root:

```python
from pathlib import Path
from explorer.tui.app import ExplorerApp
from explorer.core.event_bus import EventBus
from explorer.core.scenario_queue import ScenarioQueue
from explorer.core.bug_store import BugStore
from explorer.core.run_paths import RunPaths
from explorer.config.project_yaml import ProjectConfig

cfg = ProjectConfig(jira_project="ABC", epic_key="ABC-1", codebase_path="/tmp/c",
                    tab_url="x", bu_name=None)
rp = RunPaths.new(base=Path("/tmp/explorer-smoke"))
ExplorerApp(cfg=cfg, bus=EventBus(), queue=ScenarioQueue.from_scenarios([]),
            bugs=BugStore(mirror_path=rp.bugs_json), run_paths=rp).run()
```

Run: `uv run python tui_smoke.py`. Press `q`. Expected: header line at top with config values, two placeholder panes, one-line log strip at bottom. Press `e` to expand. Delete `tui_smoke.py`.

- [ ] **Step 6: Commit**

```bash
git add explorer/tui/__init__.py explorer/tui/app.py explorer/tui/header.py explorer/tui/log_strip.py explorer/tui/styles.tcss
git commit -m "feat(tui): add app skeleton with header and log strip"
```

---

## Task 15: `tui/sessions_pane.py` and `tui/bugs_pane.py`

**Files:**
- Create: `explorer/tui/sessions_pane.py`
- Create: `explorer/tui/bugs_pane.py`
- Modify: `explorer/tui/app.py` (replace Placeholders)

- [ ] **Step 1: Implement `bugs_pane.py`**

```python
from __future__ import annotations
from textual.widgets import ListView, ListItem, Static
from ..core.bug_store import BugStore


class BugsPane(ListView):
    def __init__(self, store: BugStore) -> None:
        super().__init__()
        self._store = store

    def refresh_from_store(self) -> None:
        self.clear()
        for bug in self._store.list_newest_first():
            self.append(ListItem(Static(f"{bug.jira_key}  {bug.title}")))
```

- [ ] **Step 2: Implement `sessions_pane.py`**

```python
from __future__ import annotations
from textual.widgets import Tree


class SessionsPane(Tree):
    def __init__(self) -> None:
        super().__init__("Sessions")
        self.show_root = False
        self._nodes: dict = {}     # session_label -> tree node
        self._subnodes: dict = {}  # tool_use_id -> tree node

    def add_session(self, session_label: str, title: str) -> None:
        node = self.root.add(f"⏵ {session_label} — {title}", expand=True)
        self._nodes[session_label] = node

    def mark_session(self, session_label: str, status: str) -> None:
        node = self._nodes.get(session_label)
        if not node:
            return
        icon = {"done": "✓", "failed": "✗", "running": "⏵"}.get(status, "·")
        # preserve the trailing title; replace only the leading icon
        current = node.label.plain
        rest = current.split(" ", 1)[1] if " " in current else current
        node.set_label(f"{icon} {rest}")

    def add_subagent(self, session_label: str, tool_use_id: str, description: str) -> None:
        parent = self._nodes.get(session_label)
        if not parent:
            return
        sub = parent.add_leaf(f"⏵ Task — {description}")
        self._subnodes[tool_use_id] = sub

    def end_subagent(self, tool_use_id: str) -> None:
        sub = self._subnodes.get(tool_use_id)
        if sub:
            current = sub.label.plain
            rest = current.split(" ", 1)[1] if " " in current else current
            sub.set_label(f"✓ {rest}")
```

- [ ] **Step 3: Modify `tui/app.py`**

Replace `compose` body to use the real panes, and add imports:

```python
from .sessions_pane import SessionsPane
from .bugs_pane import BugsPane
```

Remove `Placeholder` import. Replace the `Horizontal` block in `compose`:

```python
        self.sessions_pane = SessionsPane()
        self.sessions_pane.id = "sessions"
        self.bugs_pane = BugsPane(self._bugs)
        self.bugs_pane.id = "bugs"
        with Horizontal():
            yield self.sessions_pane
            yield self.bugs_pane
```

- [ ] **Step 4: Smoke-run again**

Re-create `tui_smoke.py` from Task 14 Step 5, run, press `q`. Expected: empty Tree on left, empty ListView on right. Delete the file.

- [ ] **Step 5: Commit**

```bash
git add explorer/tui/sessions_pane.py explorer/tui/bugs_pane.py explorer/tui/app.py
git commit -m "feat(tui): add sessions tree and bugs list panes"
```

---

## Task 16: `tui/plan_screen.py` — interview + approval

**Files:**
- Create: `explorer/tui/plan_screen.py`

- [ ] **Step 1: Implement**

```python
from __future__ import annotations
import asyncio
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, Log, Label


class PlanScreen(Screen):
    BINDINGS = [
        ("y", "approve", "approve"),
        ("q", "quit", "quit"),
    ]

    def __init__(self, *, answers: asyncio.Queue[str]) -> None:
        super().__init__()
        self._answers = answers
        self._mode = "interview"
        self._plan_yaml_text = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Planner interview — answer questions one at a time, then approve the plan.")
            self.transcript = Log(highlight=True)
            yield self.transcript
            self.input = Input(placeholder="Type your answer and press Enter…")
            yield self.input

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._mode != "interview":
            return
        text = event.value.strip()
        self.transcript.write_line(f"> {text}")
        self._answers.put_nowait(text)
        self.input.value = ""

    def append_planner_text(self, text: str) -> None:
        self.transcript.write_line(text)

    def show_plan_for_approval(self, plan_yaml_text: str) -> None:
        self._mode = "approval"
        self._plan_yaml_text = plan_yaml_text
        self.transcript.write_line("")
        self.transcript.write_line("=== PROPOSED PLAN ===")
        self.transcript.write_line(plan_yaml_text)
        self.transcript.write_line("Press y to approve, q to quit.")
        self.input.disabled = True

    def action_approve(self) -> None:
        if self._mode == "approval":
            self.dismiss(("approved", self._plan_yaml_text))

    def action_quit(self) -> None:
        self.dismiss(("cancelled", None))
```

- [ ] **Step 2: Commit**

```bash
git add explorer/tui/plan_screen.py
git commit -m "feat(tui): add planner interview + plan approval screen"
```

---

## Task 17: TUI ↔ event bus wiring + scenario runner

`ExplorerApp.on_mount` pushes the plan screen, then starts subscriptions and the runner.

**Files:**
- Modify: `explorer/tui/app.py`

- [ ] **Step 1: Add subscription methods and on_mount**

Add to `ExplorerApp`:

```python
    async def on_mount(self) -> None:
        result = await self.push_screen_wait(self.plan_screen)
        if result is None or result[0] != "approved":
            self.exit()
            return

        # Start subscriptions
        import asyncio
        asyncio.create_task(self._consume_planner_text())
        asyncio.create_task(self._consume_session_events())
        asyncio.create_task(self._consume_bug_events())
        asyncio.create_task(self._consume_queue_events())
        asyncio.create_task(self._consume_log())

        # Start scenario runner
        asyncio.create_task(self.scenario_runner())

    async def _consume_planner_text(self) -> None:
        async for ev in self._bus.subscribe("note"):
            if ev.data.get("session_label") == "planner":
                self.plan_screen.append_planner_text(ev.data.get("text", ""))

    async def _consume_session_events(self) -> None:
        async for ev in self._bus.subscribe("*"):
            if ev.type == "process_start" and ev.data.get("session_label", "").startswith("explorer"):
                label = ev.data["session_label"]
                running = next((s for s in self._queue.scenarios()
                                if self._queue.status(s.id).value == "running"), None)
                title = running.title if running else label
                self.sessions_pane.add_session(label, title)
            elif ev.type == "subagent_start":
                self.sessions_pane.add_subagent(
                    ev.data["session_label"], ev.data["tool_use_id"], ev.data["description"])
            elif ev.type == "subagent_end":
                self.sessions_pane.end_subagent(ev.data["tool_use_id"])
            elif ev.type == "process_exit":
                label = ev.data.get("session_label", "")
                rc = ev.data.get("returncode", -1)
                self.sessions_pane.mark_session(label, "done" if rc == 0 else "failed")

    async def _consume_bug_events(self) -> None:
        async for ev in self._bus.subscribe("bug_filed"):
            self.bugs_pane.refresh_from_store()
            self.header.bug_count = self._bugs.count()

    async def _consume_queue_events(self) -> None:
        async for ev in self._bus.subscribe("*"):
            if ev.type in ("scenario_proposed", "scenario_start", "scenario_done"):
                self.header.pending = self._queue.pending_count()
                self.header.discovered = self._queue.discovered_count()

    async def _consume_log(self) -> None:
        async for ev in self._bus.subscribe("note"):
            label = ev.data.get("session_label", "?")
            self.log_strip.append(f"{label}: {ev.data.get('text', '')[:120]}")
```

Also: in `compose`, instantiate `self.plan_screen` (use the answer queue and bus injected by `__main__`). Add to `__init__` parameters: `plan_screen: PlanScreen`, `scenario_runner: callable`. Wire everything through from `__main__`.

- [ ] **Step 2: Commit**

```bash
git add explorer/tui/app.py
git commit -m "feat(tui): wire event bus subscriptions and scenario runner"
```

---

## Task 18: `__main__.py` — orchestration loop

**Files:**
- Create: `explorer/__main__.py`

- [ ] **Step 1: Implement**

```python
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

from .config.cli import parse_args, resolve_config
from .core.event_bus import EventBus, Event
from .core.scenario_queue import ScenarioQueue, Scenario
from .core.bug_store import BugStore, Bug
from .core.dedup import DedupIndex
from .core.browser_lock import BrowserLock
from .core.run_paths import RunPaths
from .runner.event_log_tailer import tail_event_log
from .runner.explorer import run_explorer
from .runner.interview import run_interactive_claude
from .tui.app import ExplorerApp
from .tui.plan_screen import PlanScreen

import yaml


async def amain() -> int:
    args = parse_args(sys.argv[1:])
    project_dir = Path.cwd()
    cfg = resolve_config(args, project_dir=project_dir)

    run_paths = RunPaths.new(base=project_dir / ".explorer")
    bus = EventBus()
    queue = ScenarioQueue.from_scenarios([])
    bugs = BugStore(mirror_path=run_paths.bugs_json)
    dedup = DedupIndex.from_pairs([])
    lock = BrowserLock()

    tailer = asyncio.create_task(tail_event_log(run_paths.event_log_for_subprocess, bus))

    async def persist_events():
        async for ev in bus.subscribe("*"):
            with run_paths.events_log.open("a") as f:
                f.write(json.dumps({"type": ev.type, "data": ev.data}) + "\n")
    persist_task = asyncio.create_task(persist_events())

    # ---- Planner interview ----
    answers: asyncio.Queue[str] = asyncio.Queue()

    async def watch_for_plan():
        async for ev in bus.subscribe("plan_ready"):
            scenarios = ev.data.get("scenarios", [])
            run_paths.plan_yaml.write_text(
                yaml.safe_dump({"scenarios": scenarios}, sort_keys=False))
            for s in scenarios:
                queue.propose(Scenario(id=s["id"], title=s["title"], goal=s["goal"]))
            return scenarios

    plan_watcher = asyncio.create_task(watch_for_plan())

    prompt_planner = (Path(__file__).parent / "runner/prompts/system_planner.md").read_text()
    env = {"EXPLORER_EVENT_LOG": str(run_paths.event_log_for_subprocess)}
    planner_task = asyncio.create_task(run_interactive_claude(
        prompt=prompt_planner, cwd=Path(cfg.codebase_path),
        env_overrides=env, bus=bus, session_label="planner", answers=answers,
    ))

    # ---- TUI ----
    plan_screen = PlanScreen(answers=answers)

    async def runner():
        scen_idx = 0
        while not queue.all_done():
            scen = queue.next_pending()
            if scen is None:
                await asyncio.sleep(0.5)
                continue
            queue.mark_running(scen.id)
            scen_idx += 1
            async with lock.acquire():
                rc = await run_explorer(
                    scenario=scen, codebase_path=Path(cfg.codebase_path),
                    event_log=run_paths.event_log_for_subprocess,
                    screenshots_dir=run_paths.screenshots_dir,
                    jira_project=cfg.jira_project, epic_key=cfg.epic_key,
                    dedup=dedup, bus=bus, session_label=f"explorer-{scen_idx}",
                    bu_name=cfg.bu_name,
                )
            if rc == 0:
                queue.mark_done(scen.id)
            else:
                queue.mark_failed(scen.id, f"exit {rc}")

    async def handle_bug_filed():
        async for ev in bus.subscribe("bug_filed"):
            d = ev.data
            bugs.add(Bug(uuid=d["uuid"], jira_key=d["jira_key"], title=d["title"],
                        scenario_id=d.get("scenario_id", ""),
                        screenshot_path=d.get("screenshot_path", ""),
                        jira_url=d.get("jira_url", "")))
            dedup.record(d["title"], d["jira_key"])

    async def handle_proposed():
        async for ev in bus.subscribe("scenario_proposed"):
            d = ev.data
            queue.propose(Scenario(id=d["id"], title=d["title"], goal=d["goal"],
                                   parent_id=d.get("parent_scenario_id")))

    bug_handler = asyncio.create_task(handle_bug_filed())
    proposed_handler = asyncio.create_task(handle_proposed())

    app = ExplorerApp(
        cfg=cfg, bus=bus, queue=queue, bugs=bugs, run_paths=run_paths,
        plan_screen=plan_screen, scenario_runner=runner,
    )
    await app.run_async()

    # shutdown
    for t in (tailer, persist_task, plan_watcher, planner_task,
              bug_handler, proposed_handler):
        t.cancel()
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update `ExplorerApp.__init__` signature** to accept `plan_screen` and `scenario_runner`, store them on `self`. (Already referenced in Task 17; this commit makes the constructor accept them.)

- [ ] **Step 3: Sanity-launch**

Run: `uv run explorer --jira-project ABC --epic ABC-1 --codebase /tmp --tab-url https://example.com`
Press `q` immediately on the plan screen to confirm graceful shutdown.

- [ ] **Step 4: Commit**

```bash
git add explorer/__main__.py explorer/tui/app.py
git commit -m "feat: wire orchestration loop"
```

---

## Task 19: E2E smoke test (manual, not in CI)

**Files:**
- Create: `tests/e2e/__init__.py` (empty)
- Create: `tests/e2e/jira_mock.py`
- Create: `tests/e2e/fixtures/canned_page.html`
- Create: `tests/e2e/smoke.sh`

- [ ] **Step 1: Write `jira_mock.py`**

```python
"""Tiny FastAPI Jira mock for smoke testing.
Run: uvicorn jira_mock:app --port 5051
"""
from fastapi import FastAPI

app = FastAPI()
ISSUES: dict[str, dict] = {}
COUNTER = [1042]


@app.post("/rest/api/3/issue")
async def create_issue(body: dict):
    COUNTER[0] += 1
    key = f"ABC-{COUNTER[0]}"
    ISSUES[key] = body
    return {"key": key, "self": f"http://localhost:5051/browse/{key}"}


@app.post("/rest/api/3/issue/{key}/comment")
async def comment(key: str, body: dict):
    ISSUES.setdefault(key, {}).setdefault("comments", []).append(body)
    return {"id": str(len(ISSUES[key]["comments"]))}


@app.get("/_dump")
async def dump():
    return ISSUES
```

- [ ] **Step 2: Write `canned_page.html`**

```html
<!doctype html>
<html><body>
<h1>Test Page</h1>
<button id="save">Save</button>
<p id="status">Idle</p>
<script>/* intentionally broken: Save does nothing */</script>
</body></html>
```

- [ ] **Step 3: Write `smoke.sh`**

```bash
#!/usr/bin/env bash
# Manual end-to-end smoke. Prereqs:
#   - browser-harness installed and on PATH
#   - Chrome running with remote debugging (browser-harness handles startup)
#   - `claude` CLI on PATH, authenticated
#   - `uvicorn` and `fastapi` installed (uv sync --extra dev)
#
# Not in CI. Sanity check before releases.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

python -m http.server 5050 --directory "$ROOT/fixtures" &
SERVE_PID=$!
trap 'kill $SERVE_PID 2>/dev/null || true; kill $JIRA_PID 2>/dev/null || true' EXIT

uvicorn jira_mock:app --port 5051 &
JIRA_PID=$!
sleep 1

echo "Open Chrome to http://localhost:5050/canned_page.html"
read -p "Press Enter when ready... " _

EXPLORER_DIR=$(mktemp -d)
cd "$EXPLORER_DIR"
uv run --directory "$ROOT/../.." explorer \
    --jira-project ABC \
    --epic ABC-1042 \
    --codebase "$ROOT/fixtures" \
    --tab-url http://localhost:5050/canned_page.html

echo "--- Filed bugs (from Jira mock) ---"
curl -s http://localhost:5051/_dump | python -m json.tool
```

Make executable: `chmod +x tests/e2e/smoke.sh`

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/__init__.py tests/e2e/jira_mock.py tests/e2e/fixtures/canned_page.html tests/e2e/smoke.sh
git commit -m "test: add manual e2e smoke (Jira mock + canned page + runbook)"
```

- [ ] **Step 5: Run the smoke test manually**

Follow the instructions in `smoke.sh`. Expected:
1. TUI starts.
2. Planner asks a few questions; answer them.
3. Plan screen shows scenarios; press `y`.
4. An explorer subprocess starts, drives the canned page (clicks Save, sees nothing).
5. A bug-filer Task sub-agent appears under the explorer in the sessions pane.
6. A row appears in the bugs pane.
7. The Jira mock's `_dump` returns at least one issue.

If anything blocks, capture the trace from `.explorer/runs/<ts>/events.jsonl`.

---

## Task 20: Run the whole test suite

- [ ] **Step 1: Full pytest**

Run: `uv run pytest -v`
Expected: all unit tests pass (e2e is excluded; it's `.sh`).

- [ ] **Step 2: Compile check**

Run: `uv run python -m compileall explorer`
Expected: no syntax errors.

---

## Future work (deferrals from spec)

- `--resume <run-dir>` to replay `events.jsonl` and continue. (v1.1)
- **Startup dedup seeding from existing epic issues.** Spec section 3 calls for an MCP search at startup to seed the dedup index. v1 ships with incremental dedup only (the index grows as bugs are filed); first runs against an epic with pre-existing bugs may file duplicates. Implementing this needs either a tiny seed-dedup `claude` subprocess at startup or an extension to the planner prompt to emit an `existing_bugs` event before the plan. (v1.1)
- Pre-flight Jira permission check (create + comment + attach).
- Screenshot PII redaction.
- Time/bug budgets (`--max-bugs`, `--time-cap`).
- `r` requeue-failed keybinding wiring.
- `o`/`j` keybindings (open codebase file / open Jira URL).

These do not block v1.

---

## Acceptance criteria (from spec)

1. `explorer --jira-project … --epic … --codebase … --tab-url …` starts the TUI without errors.
2. The planner interviews the user, displays scenarios, `y` approves.
3. Each scenario spawns one explorer that ends with `scenario_done` or `failed`; both transitions render correctly in the sessions pane.
4. Filing a bug end-to-end against the Jira sandbox produces a ticket under the named epic with: title, body containing scenario + symptom + suggested fix referencing real codebase files/lines, screenshot attachment.
5. A second observation matching an existing bug results in a comment, not a duplicate.
6. Header counts stay consistent with `events.jsonl` after a full run.

