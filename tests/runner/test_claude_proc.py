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


def test_parse_non_task_tool_use_does_not_emit_subagent_start():
    """Non-Task tool_use must not create a subagent tree node."""
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "tu_2", "name": "Bash", "input": {"command": "ls"}}
    ]}})
    events = parse_stream_line(line, session_label="explorer-1")
    assert not any(e.type == "subagent_start" for e in events)


def test_parse_bash_tool_use_emits_note_for_log_strip():
    """Bash tool_use should surface to the log strip as a note."""
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "tu_3", "name": "Bash",
         "input": {"command": "browser-harness -c 'capture_screenshot()'"}}
    ]}})
    events = parse_stream_line(line, session_label="explorer-1")
    notes = [e for e in events if e.type == "note"]
    assert len(notes) == 1
    assert "browser-harness" in notes[0].data["text"]
    assert notes[0].data["text"].startswith("🌐")


def test_parse_grep_tool_use_emits_note():
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "tu_4", "name": "Grep",
         "input": {"pattern": "saveButton"}}
    ]}})
    events = parse_stream_line(line, session_label="explorer-1")
    notes = [e for e in events if e.type == "note"]
    assert len(notes) == 1
    assert "saveButton" in notes[0].data["text"]


def test_parse_malformed_returns_empty():
    events = parse_stream_line("not json", session_label="x")
    assert events == []
