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
