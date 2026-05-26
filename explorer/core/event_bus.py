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
