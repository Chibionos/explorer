"""Hardcoded interview questions, asked locally by the TUI.

`claude -p` is single-shot — we can't do multi-turn interview through stdin.
So the TUI collects answers itself, then one claude call turns them into a plan.
"""
from __future__ import annotations

INTERVIEW_QUESTIONS: list[str] = [
    "What flows, pages, or features are highest priority to explore? "
    "(1-3 sentences — e.g. 'the canvas, properties panel, save flow')",
    "Any known-weak areas, recent changes, or specific user complaints to focus on? "
    "(type 'none' if not sure)",
    "Anything to AVOID — paid actions, destructive ops, production data, "
    "specific buttons? (type 'nothing' if no constraints)",
    "Depth: type 'smoke' (5-10 scenarios) or 'thorough' (20+)?",
]
