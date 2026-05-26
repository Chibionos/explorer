# explorer

A long-running TUI for **AI-driven exploratory testing** of web apps. Drives a
real Chrome tab via [browser-harness](https://github.com/anthropics/browser-harness),
spawns Claude Code subprocesses to run scenarios you (or a coding agent) approved,
files bugs to a Jira epic with **code-aware fix suggestions** by Read/Grep-ing the
product source, and optionally maintains a Confluence page as a per-scenario
evidence record.

Designed so **any coding agent can start it, watch it, and course-correct it** —
all via the CLI.

```
┌─ explorer ─ Bugs: 7 │ Pending: 4 │ Discovered: 11 │ Jira: AE / Epic AE-1546 │ Code: ~/r/flow-workbench
├──────────────────────────────────────────┬────────────────────────────────────
│ SESSIONS                                 │ BUGS
│ ▼ explorer #3   ⏵ running   00:02:14     │ AE-1551  Modal close (X) misses 4px
│   "Test promo code edge cases"           │ AE-1550  Settings save stays disabled
│   ├─ Task bug-filer #a   ✓ filed AE-1551 │ AE-1549  Helper text echoes invalid
│   ├─ Task bug-filer #b   ⏵ analyzing code│ AE-1548  Monaco traps Tab focus
│   └─ Task proposer       ✓ +2 scenarios  │ AE-1547  Label has no maxLength
│ ▽ explorer #2   ✓ done      02:11        │ …
│ ▽ explorer #1   ✓ done      01:47        │
├──────────────────────────────────────────┴────────────────────────────────────
│ LOG  (last 8 lines, e to expand)
│ explorer-3: 🌐 browser-harness -c 'capture_screenshot()'
│ explorer-3: 📋 Jira create: Modal close (X) misses 4px on narrow viewport
│ explorer-3: 📄 Read packages/workbench/src/components/Modal.tsx
│ explorer-3: 🔍 Grep "data-testid=\"modal-close\""
└─ q quit  p pause  e expand  t pick tab  ↑↓ navigate  enter open ──────────────
```

## Why use it

- **No babysitting.** Set up a plan, hit `y`, walk away. The runner cycles
  scenarios serially across one Chrome tab; bug-filer sub-agents run in parallel.
- **Real codebase context.** When a bug-filer agent finds something, it `Read`s
  the product source to identify suspect files and writes a fix suggestion in
  the Jira ticket — ready for any coding agent to pick up.
- **Designed for coding-agent orchestration.** Every flag, every state file, every
  subcommand is non-interactive-friendly. Coding agents can start it, query
  status from outside via `explorer status`, watch events with `explorer tail`,
  swap plans on `--resume`, change target tab via `--pick-tab`.

## Install

Requires Python ≥ 3.11, [uv](https://docs.astral.sh/uv/), the
[`claude`](https://docs.claude.com/claude-code) CLI on PATH (authenticated), and
the `browser-harness` CLI attached to a running Chrome session.

```bash
# clone + install globally as an editable uv tool
git clone https://github.com/Chibionos/explorer.git
cd explorer
uv tool install --reinstall --editable .

# verify
which explorer            # → ~/.local/bin/explorer
explorer --help
```

To upgrade after pulling new code: `uv tool install --reinstall --editable .`

## Quickstart

```bash
# from any directory — config saves to .explorer/project.yaml here
explorer \
  --jira-project AE \
  --epic AE-1546 \
  --codebase /home/me/r/your-product \
  --plan plans/your-plan.yaml -y --continuous
```

If you omit `--tab-url`, a tab picker pops in the TUI listing every open Chrome
tab. Pick one with `↑↓ Enter`.

## How a coding agent uses this

```bash
# 1. Set up the project (one time per cwd)
explorer \
  --jira-project AE --epic AE-1546 \
  --codebase /home/me/r/flow-workbench \
  --confluence-space ENG \
  --plan plans/eval-flows.yaml -y --continuous

# 2. From a separate shell, watch progress
explorer status                  # one-shot human summary
explorer status --json           # machine-readable for parsing
explorer tail                    # stream of formatted events
explorer tail --filter bug_filed # only bug events

# 3. Course-correct: swap to a different plan, resume after a stop, etc.
explorer --resume --continuous   # pick up the latest run
explorer --resume --pick-tab     # repick the tab before continuing
```

## CLI reference

### `explorer` (default: launch the TUI)

| Flag | Purpose |
|------|---------|
| `--jira-project KEY` | Jira project key. Required on first run. |
| `--epic KEY` | Jira epic key for bug filing. Required on first run. |
| `--codebase PATH` | Path to the product source tree. Required on first run. |
| `--tab-url URL` | Browser tab the explorer should target. Omit → TUI picker. |
| `--bu-name NAME` | `browser-harness` daemon name (default: harness default). |
| `--plan PATH` | YAML plan file. Skips the in-TUI planner interview. |
| `-y, --yes` | Auto-approve when `--plan` is set. |
| `--continuous` | When the queue empties, requeue the original scenarios as a fresh round. Press `q` to stop. |
| `--resume [PATH]` | Continue a previous run. Without a value, picks the latest. |
| `--pick-tab` | Force the tab picker even when a tab is configured. |
| `--confluence-space KEY` | Create a new Confluence page per run and update it as scenarios complete. |
| `--confluence-page ID` | Append scenarios to an existing Confluence page (persistent evidence log). |

### `explorer status`

One-shot summary of the current/latest run. `--json` for machine output.

### `explorer tail`

Stream events.jsonl with friendly formatting and emoji prefixes. `--filter <type>`
to narrow (e.g. `--filter bug_filed`).

## Plan file format

```yaml
scenarios:
  - id: short-kebab-id           # unique within the file
    title: One-line description
    goal: |
      1-3 sentences telling the explorer agent what to try and what
      kinds of bugs to be alert for (UI/UX, functional, intuitive).
  - id: ...
```

Any coding agent can write a plan file and pass it via `--plan`. Sample under
[`plans/`](plans/).

## Architecture (one screen)

```
explorer/             # the orchestrator (single Python process, Textual TUI)
├── __main__.py       # subcommand routing + amain() orchestration loop
├── cli/              # `status` and `tail` non-TUI subcommands
├── config/           # CLI flags + project.yaml persistence
├── core/             # pure state: EventBus, ScenarioQueue, BugStore, DedupIndex,
│                     #             BrowserLock, RunPaths
├── runner/           # subprocess drivers
│   ├── claude_proc.py        # spawns `claude --output-format stream-json`
│   ├── explorer.py           # per-scenario explorer subprocess
│   ├── planner.py            # one-shot planner subprocess from interview answers
│   ├── confluence.py         # confluence-writer subprocess on scenario_done
│   ├── tabs.py               # browser-harness chrome-tab listing
│   ├── interview.py          # interactive stdin-pipe variant
│   ├── event_log_tailer.py   # tails the sentinel JSONL → EventBus
│   └── prompts/              # markdown system prompts for each subprocess role
└── tui/              # Textual widgets: header, sessions tree, bugs list,
                      # log strip, plan screen, tab picker
```

### Concurrency model

- **One explorer at a time.** `BrowserLock` serializes access to your one Chrome tab.
- **Bug-filers run in parallel** as `Task` sub-agents inside the same explorer
  subprocess (Claude Code's `Task` tool, with `run_in_background=true`).
- **Confluence updates happen async** after each `scenario_done` event — they
  don't block the next scenario from starting.

### Two event channels

1. `--output-format stream-json` from each `claude` subprocess → orchestrator
   parses to get sub-agent nesting (Task tool_use → `subagent_start`/`subagent_end`)
   and live action visibility (every Bash/Read/Grep/MCP call → `note`).
2. **Sentinel JSONL** at `.explorer/runs/<ts>/explorer_event_log.jsonl`. The
   explorer subprocess `Bash`-appends structured events here
   (`bug_observed`, `bug_filed`, `scenario_done`, `plan_ready`,
   `confluence_page_ready`, …). Canonical truth for queue + bug state.

### State on disk

```
.explorer/
├── project.yaml          # CLI defaults: jira_project, epic_key, codebase_path,
│                         # tab_url, bu_name, confluence_space, confluence_page
└── runs/<timestamp>/
    ├── plan.yaml         # the approved scenarios
    ├── events.jsonl      # full event log (replayable; status/tail read this)
    ├── explorer_event_log.jsonl   # raw sentinel events from subprocesses
    ├── bugs.json         # mirror of bugs filed in this run
    └── screenshots/<uuid>.png
```

## Confluence integration

Two modes via flags:

- `--confluence-space KEY` — creates a new page titled `[Explorer] <run timestamp>`
  in that space. Each `scenario_done` appends a new section: title, goal,
  status, bugs filed (with Jira links), and the list of screenshot paths in the
  run dir.
- `--confluence-page ID` — appends to an existing page. Useful for a rolling
  evidence log across many runs.

The page ID is persisted to `project.yaml` after first run, so subsequent
runs from the same cwd default to it.

**Note on screenshots:** v1 references screenshots by their filesystem paths in
the run directory rather than embedding them. We're tracking inline image
embedding as a follow-up.

**Note on video:** real screen recording is deferred; we ship one screenshot
per bug observation (the explorer takes one to attach to the bug report). Adding
a periodic filmstrip + ffmpeg assembly is on the roadmap.

## Bug filing flow

```
[explorer subprocess]
    sees bug → screenshot saved → bug_observed event written
                                        ↓
                   Task(bug-filer, run_in_background=true)
                                        ↓
                 [bug-filer claude sub-agent, cwd = codebase]
                   ├─ checks known-bug list (dedup)
                   ├─ Read/Grep over product source for suspect code
                   ├─ either mcp__atlassian__createJiraIssue
                   │       (Bug under the epic, body has Symptom +
                   │        Steps + Suspected code + Suggested fix)
                   ├─ or    mcp__atlassian__addCommentToJiraIssue
                   │       (existing key, fresh repro)
                   └─ writes bug_filed / bug_dup_comment event
```

Dedup index uses normalized title (lowercased, punctuation stripped, stopwords
removed) so "Modal close (X) misses 4px" and "modal close X misses 4px" hash to
the same key.

## Testing

```bash
uv run pytest -v       # 55 tests (core state + event parsing)
```

TUI rendering itself isn't unit-tested (Textual snapshots are flaky for nested
reactive trees); panes stay dumb so unit-tests of state suffice. There's a
manual E2E smoke at `tests/e2e/smoke.sh` (FastAPI Jira mock + canned HTML page).

## Built with

- [Textual](https://textual.textualize.io/) for the TUI
- [browser-harness](https://github.com/anthropics/browser-harness) for the
  Chrome CDP bridge
- [Claude Code](https://docs.claude.com/claude-code) for the per-scenario
  subprocesses (uses MCP for Jira/Confluence; Read/Grep for codebase analysis)
- [uv](https://docs.astral.sh/uv/) for package management

## License

MIT.
