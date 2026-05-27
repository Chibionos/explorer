from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from typing import Mapping
from ..core.event_bus import EventBus, Event

# Alias for readability; spawns a subprocess from an argv list (no shell).
_spawn = asyncio.create_subprocess_exec


class ProcHolder:
    """Mutable holder so the orchestrator can SIGTERM the active claude
    subprocess (e.g. when the user presses 'r' to restart a stuck explorer).
    Set by run_claude when a holder is passed in.
    """
    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None

    def set(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc

    def terminate(self) -> bool:
        if self.proc is None or self.proc.returncode is not None:
            return False
        try:
            self.proc.terminate()
            return True
        except ProcessLookupError:
            return False


def _summarize_tool_use(name: str, inp: dict) -> str:
    """Format a tool_use block into a short human-readable line for the log strip."""
    if name == "Bash":
        cmd = (inp.get("command") or "").strip().replace("\n", " ⏎ ")
        if "browser-harness" in cmd:
            return f"🌐 {cmd[:200]}"
        return f"$ {cmd[:200]}"
    if name == "Read":
        return f"📄 Read {inp.get('file_path', '')[:200]}"
    if name == "Glob":
        return f"📂 Glob {inp.get('pattern', '')[:200]}"
    if name == "Grep":
        return f"🔍 Grep {inp.get('pattern', '')[:200]}"
    if name == "Write":
        return f"✏️  Write {inp.get('file_path', '')[:200]}"
    if name == "Edit":
        return f"✏️  Edit {inp.get('file_path', '')[:200]}"
    if name.startswith("mcp__atlassian__"):
        method = name.replace("mcp__atlassian__", "")
        # for createJiraIssue, show the summary if present
        if "createJiraIssue" in method:
            summary = inp.get("summary", "")
            return f"📋 Jira create: {summary[:180]}"
        if "addCommentToJiraIssue" in method:
            return f"📋 Jira comment on issue"
        return f"📋 {method}"
    return f"🔧 {name}"


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
                    # Note goes to both the log strip AND the sessions tree
                    # as a 📝 narrative leaf (truncated).
                    events.append(Event(type="note", data={
                        "session_label": session_label,
                        "text": text[:400],
                    }))
                    events.append(Event(type="narrative", data={
                        "session_label": session_label,
                        "text": text[:200],
                    }))
            elif block.get("type") == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {}) or {}
                summary = _summarize_tool_use(name, inp)
                if name == "Task":
                    events.append(Event(type="subagent_start", data={
                        "session_label": session_label,
                        "tool_use_id": block.get("id", ""),
                        "description": inp.get("description", ""),
                        "subagent_type": inp.get("subagent_type", ""),
                    }))
                else:
                    # log strip line
                    events.append(Event(type="note", data={
                        "session_label": session_label,
                        "text": summary,
                    }))
                    # sessions tree leaf
                    events.append(Event(type="tool_action", data={
                        "session_label": session_label,
                        "tool_use_id": block.get("id", ""),
                        "tool_name": name,
                        "summary": summary,
                    }))
    elif rec.get("type") == "user":
        for block in rec.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                events.append(Event(type="subagent_end", data={
                    "session_label": session_label,
                    "tool_use_id": block.get("tool_use_id", ""),
                    "is_error": bool(block.get("is_error", False)),
                }))
    return events


async def _drain_stream(stream: asyncio.StreamReader, sink) -> None:
    """Read lines from stream and pass each raw line to sink(line)."""
    async for raw in stream:
        await sink(raw)


async def run_claude(
    *, prompt: str, cwd: Path, env_overrides: Mapping[str, str],
    bus: EventBus, session_label: str,
    proc_holder: "ProcHolder | None" = None,
    exit_grace_seconds: float = 5.0,
) -> int:
    """Spawn the claude CLI and forward its stream-json events to the bus.

    Watchdog: claude's Task tool can spawn grandchildren that inherit stdout.
    When claude itself exits but a grandchild keeps the pipe alive, the
    naive `async for raw in proc.stdout` reader would wait forever for EOF.
    Here we race the stream reader against `proc.wait()`. Once the process
    is gone, we give the reader a short grace period to drain any remaining
    buffered output, then close the streams and move on.
    """
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
    if proc_holder is not None:
        proc_holder.set(proc)
    await bus.publish(Event(type="process_start",
                            data={"session_label": session_label, "pid": proc.pid}))

    assert proc.stdout is not None and proc.stderr is not None

    async def handle_stdout(raw: bytes) -> None:
        for ev in parse_stream_line(raw.decode("utf-8", errors="replace"),
                                    session_label=session_label):
            await bus.publish(ev)

    async def handle_stderr(raw: bytes) -> None:
        # Forward non-empty stderr as note events so anything claude
        # complains about shows up in the log strip. Also prevents the
        # stderr pipe from filling and blocking the child.
        text = raw.decode("utf-8", errors="replace").strip()
        if text:
            await bus.publish(Event(type="note", data={
                "session_label": session_label,
                "text": f"stderr: {text[:300]}",
            }))

    stdout_task = asyncio.create_task(_drain_stream(proc.stdout, handle_stdout))
    stderr_task = asyncio.create_task(_drain_stream(proc.stderr, handle_stderr))
    wait_task = asyncio.create_task(proc.wait())

    # Wait for the process to exit. Stream drains may continue past that
    # if grandchildren are still holding fds open, so we give them a
    # bounded grace period and then close the streams ourselves.
    await wait_task
    rc = proc.returncode if proc.returncode is not None else -1

    try:
        await asyncio.wait_for(
            asyncio.gather(stdout_task, stderr_task, return_exceptions=True),
            timeout=exit_grace_seconds,
        )
    except asyncio.TimeoutError:
        # A grandchild is still holding the pipe open. Force-close.
        for s in (proc.stdout, proc.stderr):
            try:
                s._transport.close()  # type: ignore[attr-defined]
            except Exception:
                pass
        for t in (stdout_task, stderr_task):
            t.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        await bus.publish(Event(type="note", data={
            "session_label": session_label,
            "text": f"watchdog: subprocess exited but pipe held open by "
                    f"grandchild; forced close after {exit_grace_seconds}s",
        }))

    await bus.publish(Event(type="process_exit",
                            data={"session_label": session_label, "returncode": rc}))
    return rc
