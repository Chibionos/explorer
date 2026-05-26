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
