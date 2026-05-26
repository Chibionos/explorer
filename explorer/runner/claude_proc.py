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


async def run_claude(
    *, prompt: str, cwd: Path, env_overrides: Mapping[str, str],
    bus: EventBus, session_label: str,
    proc_holder: "ProcHolder | None" = None,
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
    if proc_holder is not None:
        proc_holder.set(proc)
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
