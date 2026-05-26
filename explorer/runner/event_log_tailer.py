from __future__ import annotations
import asyncio
import json
from pathlib import Path
from ..core.event_bus import EventBus, Event


async def tail_event_log(path: Path, bus: EventBus, *, poll_interval: float = 0.1) -> None:
    path.touch()
    pos = 0
    await asyncio.sleep(0)  # yield to let subscribers register before first poll
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
