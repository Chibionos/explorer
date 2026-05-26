"""Tiny FastAPI Jira mock for smoke testing.
Run: uvicorn jira_mock:app --port 5051
"""
from fastapi import FastAPI

app = FastAPI()
ISSUES: dict[str, dict] = {}
COUNTER = [1042]


@app.post("/rest/api/3/issue")
async def create_issue(body: dict):
    COUNTER[0] += 1
    key = f"ABC-{COUNTER[0]}"
    ISSUES[key] = body
    return {"key": key, "self": f"http://localhost:5051/browse/{key}"}


@app.post("/rest/api/3/issue/{key}/comment")
async def comment(key: str, body: dict):
    ISSUES.setdefault(key, {}).setdefault("comments", []).append(body)
    return {"id": str(len(ISSUES[key]["comments"]))}


@app.get("/_dump")
async def dump():
    return ISSUES
