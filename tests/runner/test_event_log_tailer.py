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
