#!/usr/bin/env bash
# Manual end-to-end smoke. Prereqs:
#   - browser-harness installed and on PATH
#   - Chrome running with remote debugging (browser-harness handles startup)
#   - `claude` CLI on PATH, authenticated
#   - `uvicorn` and `fastapi` installed (uv sync --extra dev)
#
# Not in CI. Sanity check before releases.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

python -m http.server 5050 --directory "$ROOT/fixtures" &
SERVE_PID=$!
trap 'kill $SERVE_PID 2>/dev/null || true; kill $JIRA_PID 2>/dev/null || true' EXIT

uvicorn jira_mock:app --port 5051 &
JIRA_PID=$!
sleep 1

echo "Open Chrome to http://localhost:5050/canned_page.html"
read -p "Press Enter when ready... " _

EXPLORER_DIR=$(mktemp -d)
cd "$EXPLORER_DIR"
uv run --directory "$ROOT/../.." explorer \
    --jira-project ABC \
    --epic ABC-1042 \
    --codebase "$ROOT/fixtures" \
    --tab-url http://localhost:5050/canned_page.html

echo "--- Filed bugs (from Jira mock) ---"
curl -s http://localhost:5051/_dump | python -m json.tool
