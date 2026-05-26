# explorer

A TUI that points Claude Code at a web app and tells it to find bugs.

You give it a Jira epic, one or more codebase paths, a Chrome tab, and
a plan. It opens the tab, drives the UI, notices when something's off,
reads the product source to figure out which file is at fault, files a
Jira ticket with a suggested fix, and moves to the next scenario. It
runs unattended for hours, and any coding agent can start it, peek at
it from outside, or kill a stuck explorer without quitting the TUI.

<p align="center">
  <img src="docs/img/hero.jpg" alt="An AI character inspecting a web browser, with a terminal showing bug findings in the background" width="720"/>
</p>

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

## How it works in practice

Set up a plan, hit `y`, walk away. The runner takes scenarios one at a
time on your single Chrome tab. Inside each scenario, bug-filer
sub-agents fan out in parallel the moment the explorer spots something
suspicious.

The bug-filer is the trick. It opens your codebase, greps for the code
behind the broken UI, identifies the likely file and line range, and
writes a fix suggestion into the Jira body. So the tickets that land in
your epic aren't just "this is broken, here's a screenshot" — they read
like a starting point an engineer (or a coding agent) can act on
without re-investigating from scratch.

Pass `--codebase` multiple times if a UI symptom can trace back to more
than one repo (frontend + backend, or a constellation of services). The
bug-filer searches across all of them and references whichever repo's
file is responsible.

Everything talks back through the CLI, not just the TUI. `explorer
status` summarizes a live or finished run. `explorer tail` streams the
event feed. `--resume` continues a stopped session. `--pick-tab`
retargets. If you're building automation on top of this, you'll spend
more time on those subcommands than in the TUI.

## Install

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), the
[`claude`](https://docs.claude.com/claude-code) CLI authenticated on
PATH, and `browser-harness` attached to a Chrome session.

```bash
git clone https://github.com/Chibionos/explorer.git
cd explorer
uv tool install --reinstall --editable .
which explorer            # → ~/.local/bin/explorer
explorer --help
```

Re-run the install line after pulling new code. It's an editable
install so most edits are live, but a fresh dependency lands properly
this way.

## Quickstart

```bash
# single repo
explorer \
  --jira-project AE \
  --epic AE-1546 \
  --codebase /home/me/r/your-product \
  --plan plans/your-plan.yaml -y --continuous

# multi-repo (FE + BE + shared) — bug-filer searches across all of them
explorer \
  --jira-project AE --epic AE-1546 \
  --codebase /home/me/r/flow-workbench \
  --codebase /home/me/r/agents-service \
  --codebase /home/me/r/uipath-python \
  --plan plans/eval-flows.yaml -y --continuous
```

If you skip `--tab-url`, a picker pops in the TUI listing every open
Chrome tab. Arrow keys + Enter.

## Running it from another agent

```bash
# 1. Set it up (once per cwd; saves to .explorer/project.yaml)
explorer \
  --jira-project AE --epic AE-1546 \
  --codebase /home/me/r/flow-workbench \
  --confluence-space ENG \
  --plan plans/eval-flows.yaml -y --continuous

# 2. Watch from another shell
explorer status                   # human-readable summary
explorer status --json            # parseable
explorer tail                     # live event feed
explorer tail --filter bug_filed  # only bugs

# 3. Course-correct
explorer --resume --continuous    # pick up the latest run
explorer --resume --pick-tab      # repick the tab before continuing
```

## CLI reference

`explorer` (no subcommand) launches the TUI.

| Flag | Purpose |
|------|---------|
| `--jira-project KEY` | Jira project key. Required on first run. |
| `--epic KEY` | Jira epic key for bug filing. Required on first run. |
| `--codebase PATH` | Path to a product source tree. Required on first run; repeatable to feed the bug-filer multiple repos so it can find code that spans services. |
| `--tab-url URL` | Browser tab to target. Omit to get a picker. |
| `--bu-name NAME` | `browser-harness` daemon name. |
| `--plan PATH` | YAML plan file. Skips the in-TUI interview. |
| `-y`, `--yes` | Auto-approve when `--plan` is set. |
| `--continuous` | Cycle rounds once the queue empties. `q` to stop. |
| `--resume [PATH]` | Continue a previous run. No value = latest. |
| `--pick-tab` | Force the tab picker. |
| `--confluence-space KEY` | Create a fresh Confluence page per run. |
| `--confluence-page ID` | Append to an existing Confluence page. |

`explorer status` prints a one-shot summary; `--json` for parsing.

`explorer tail` streams `events.jsonl` with emoji prefixes; `--filter
<type>` to narrow.

## Plan file format

```yaml
scenarios:
  - id: short-kebab-id           # unique within the file
    title: One-line description
    goal: |
      1-3 sentences telling the explorer what to try and what
      kinds of bugs to be alert for (UI/UX, functional, intuitive).
```

Any agent can write a plan file and pass it via `--plan`. Samples
under [`plans/`](plans/).

## Architecture

```
explorer/
├── __main__.py       # subcommand routing + amain() orchestration loop
├── cli/              # status and tail non-TUI subcommands
├── config/           # CLI flags + project.yaml persistence
├── core/             # pure state: EventBus, ScenarioQueue, BugStore,
│                     # DedupIndex, BrowserLock, RunPaths
├── runner/           # subprocess drivers + the markdown prompts
│   ├── claude_proc.py        # spawns claude --output-format stream-json
│   ├── explorer.py           # per-scenario explorer subprocess
│   ├── planner.py            # one-shot planner from interview answers
│   ├── confluence.py         # confluence writer on scenario_done
│   ├── tabs.py               # CDP-based chrome tab listing
│   ├── event_log_tailer.py   # tails the sentinel JSONL to the event bus
│   └── prompts/              # markdown prompts for every subprocess role
└── tui/              # Textual widgets
```

### Concurrency

One explorer at a time, because there's one Chrome tab. The
`BrowserLock` serializes scenarios. Inside each explorer, bug-filer
sub-agents run in parallel via Claude Code's `Task` tool with
`run_in_background=true`. Confluence updates fire after each
`scenario_done` and don't block the next scenario from starting.

### Two event channels

You need both. They do different jobs.

`stream-json` from each `claude` subprocess feeds sub-agent nesting
(Task tool calls become `subagent_start` / `subagent_end`) and live
visibility into every Bash / Read / Grep / MCP call as a `note`. That's
what powers the log strip and the expandable timeline in the TUI.

A sentinel JSONL file at `.explorer/runs/<ts>/explorer_event_log.jsonl`
is the canonical record. The explorer subprocess shell-appends
structured events (`bug_observed`, `bug_filed`, `scenario_done`,
`plan_ready`, `confluence_page_ready`) here. Parsing English out of the
LLM is unreliable; this file is the truth.

### State on disk

```
.explorer/
├── project.yaml          # CLI defaults: jira_project, epic_key,
│                         # codebase_paths (list), tab_url, bu_name,
│                         # confluence_space, confluence_page
└── runs/<timestamp>/
    ├── plan.yaml         # the approved scenarios
    ├── events.jsonl      # full event log; status/tail read this
    ├── explorer_event_log.jsonl   # raw sentinel events
    ├── bugs.json         # mirror of bugs filed in this run
    └── screenshots/<uuid>.png
```

## Confluence integration

`--confluence-space KEY` creates a fresh page per run titled `[Explorer]
<timestamp>` in that space. Each `scenario_done` appends a new section
with title, goal, status, bugs filed (with Jira links), and screenshot
paths.

`--confluence-page ID` appends to an existing page instead. Pick this
if you want a rolling evidence log across many runs.

Either way, the page ID gets persisted to `project.yaml` after first
run, so subsequent runs from the same cwd default to it.

A caveat: v1 references screenshots by filesystem path in the run dir
rather than embedding them inline in the Confluence page. Inline image
embedding is a known follow-up. Video recording is also deferred.
Today you get one screenshot per bug observation, and a periodic
filmstrip + ffmpeg assembly path is on the roadmap if it matters to
anyone.

## How a bug gets filed

```
[explorer subprocess]
    sees bug → screenshot saved → bug_observed event written
                                        ↓
                   Task(bug-filer, run_in_background=true)
                                        ↓
                 [bug-filer claude sub-agent, cwd = primary codebase]
                   ├─ checks known-bug list (signature dedup)
                   ├─ Read/Grep over the primary codebase + any
                   │  additional --codebase paths (absolute) for
                   │  suspect code
                   ├─ either mcp__atlassian__createJiraIssue
                   │       (Bug under the epic, body has Symptom +
                   │        Steps + Suspected code + Suggested fix)
                   ├─ or    mcp__atlassian__addCommentToJiraIssue
                   │       (existing key, fresh repro)
                   └─ writes bug_filed / bug_dup_comment event
```

Dedup is on the normalized title: lowercased, punctuation stripped,
stopwords removed. "Modal close (X) misses 4px" and "modal close X
misses 4px" hash to the same key, and the second discovery becomes a
comment on the first ticket instead of a new one.

## Testing

```bash
uv run pytest -v       # 55 tests across core state and event parsing
```

TUI rendering isn't unit-tested. Textual snapshot tests are flaky for
nested reactive trees, so the widgets stay dumb and the state modules
carry the coverage. There's a manual E2E smoke at `tests/e2e/smoke.sh`
(FastAPI Jira mock + canned HTML page) for the rare full-stack check.

## Spec

Want to build your own version of this in a different language or
stack? [`SPEC.md`](SPEC.md) is the seed. It captures the invariants, the
event model, the prompt contracts, the lifecycle, and the 14 specific
traps the reference build hit along the way.

## Built with

[Textual](https://textual.textualize.io/),
[browser-harness](https://github.com/anthropics/browser-harness),
[Claude Code](https://docs.claude.com/claude-code), and
[uv](https://docs.astral.sh/uv/).

## License

MIT.
