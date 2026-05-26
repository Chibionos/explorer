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
