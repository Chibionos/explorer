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
