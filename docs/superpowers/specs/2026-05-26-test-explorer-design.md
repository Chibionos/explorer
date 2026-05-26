# Design: Claude Code Test Explorer

**Date:** 2026-05-26
**Status:** Approved (sections 1–5)
**Author:** Chibi (with Claude)

## Purpose

A long-running TUI tool that drives a real Chrome tab via `browser-harness` and
spawns Claude Code subprocesses to perform exploratory testing of a product.
When it finds a UI/UX/functional/non-intuitive bug, a sub-agent reads the
product's codebase, files a Jira ticket under a "Bug Explorer" Epic with
screenshot + suggested fix details, and the orchestrator keeps going until the
scenario queue is empty.

The tool is meant to be left running unattended for hours; the TUI provides
real-time visibility into which sub-agent is doing what and what bugs have been
filed so far.

## Non-goals

- Automated regression testing (this is exploratory).
- Headless cloud runs (single local browser tab the user gives it).
- Multi-tenant / multi-project parallel runs.
- Fixing the bugs (filer writes fix-details for downstream coding agents).

## Inputs

Supplied on first run via CLI flags; persisted to `.explorer/project.yaml`:

- `--jira-project KEY` — e.g. `ABC`
- `--epic KEY` — the "Bug Explorer" epic key, e.g. `ABC-1042`
- `--codebase PATH` — absolute path to the product source tree
- `--tab-url URL` — the page the user has already opened in their Chrome tab
- `--bu-name NAME` — optional `browser-harness` daemon name (default: harness default)

Subsequent runs in the same directory read `.explorer/project.yaml` and accept
overrides via the same flags.

## Runtime topology (Section 1)

Single Python process running a Textual TUI. It spawns Claude Code
subprocesses serially because they share the user's single browser tab. Each
explorer subprocess uses Claude Code's `Task` tool to spawn its own in-process
sub-agents (bug-filer, scenario-proposer), which are nested children of that
explorer.

```
explorer (Python+Textual orchestrator)
├── ScenarioQueue, BugStore, BrowserLock, EventBus
├── planner          : `claude -p` (one-shot interview → plan.yaml)
└── explorer-N       : `claude --output-format stream-json -p ...`
                       cwd = $codebase_path
    ├─ Task bug-filer        (parallel, in-background)
    └─ Task scenario-proposer
```

- One explorer at a time. The lock is enforced by an explicit
  `asyncio.Lock` in `core/browser_lock.py` so that a future scenario cannot
  start until the previous explorer's Task sub-agents (including parallel
  bug-filers) have finished and the process has exited.
- Sub-agents inherit `cwd = codebase` so they can `Read`/`Grep` product code.
- Sub-agents inherit `mcp__atlassian__*` from the user's MCP config.
- Bug-filers can run in parallel via `Task(... run_in_background=true)`; the
  explorer waits for them all before exiting.

## TUI layout (Section 2)

```
┌─ explorer ─ Bugs: 7 │ Pending: 4 │ Discovered: 11 │ Jira: ABC / Epic ABC-1042 │ Code: ~/r/foo ─┐
├──────────────────────────────────────────┬──────────────────────────────────────────────────┤
│ SESSIONS                                 │ BUGS                                              │
│ ▼ explorer #3   ⏵ running   00:02:14     │ ABC-1051  Checkout total ignores promo on refresh│
│   "Test promo code edge cases"           │ ABC-1050  Empty cart shows "1 item" in mini-cart  │
│   ├─ Task bug-filer #a   ✓ filed ABC-1051│ ABC-1049  Settings save button stays disabled... │
│   ├─ Task bug-filer #b   ⏵ analyzing code│ ABC-1048  /reports throws 500 when range > 1y    │
│   └─ Task proposer       ✓ +2 scenarios  │ ABC-1047  Modal close (X) misses 4px on mobile   │
│ ▽ explorer #2   ✓ done      02:11        │                                                   │
│ ▽ planner       ✓ done      00:42        │                                                   │
├──────────────────────────────────────────┴──────────────────────────────────────────────────┤
│ LOG (last action: explorer #3 → bug-filer #b reading src/checkout/PromoBanner.tsx)          │
└──────── q quit  p pause  e expand  ↑↓ navigate  enter open  ────────────────────────────────┘
```

- **Header**: live counters + project context, always visible.
- **Sessions pane** (left): tree, active explorer expanded, older ones
  collapsed. Each `Task` sub-agent renders as a child line.
- **Bugs pane** (right): newest-first `<KEY>  <title>`. Enter opens detail.
- **Bottom log strip**: one-line tail; `e` to toggle 10-line expansion.
- **Keys**: `q` quit, `p` pause queue, `r` resume / requeue selected, `e`
  expand log, `↑↓ enter` inspect, `o` open codebase file in `$EDITOR`, `j` open
  Jira URL.
- **Planner interview screen**: before the plan-approval overlay, a
  full-screen scrollable transcript view shows the planner subprocess's
  questions one at a time; the user types answers into a single-line input at
  the bottom (Enter submits). When the planner emits its final `plan.yaml`,
  the screen transitions to the plan-approval overlay.
- **Pre-run plan-approval overlay**: full-screen list of proposed scenarios
  with goals; `y` approve / `e` edit in `$EDITOR` / `q` quit.

## Data model + event flow (Section 3)

On disk (everything else is in-memory):

```
.explorer/
├── project.yaml
└── runs/2026-05-26_14-22/
    ├── plan.yaml
    ├── events.jsonl          # canonical replay log
    ├── bugs.json             # mirror of filed bugs
    └── screenshots/<bug-uuid>.png
```

### Event types

| Event | Source | Fields |
|---|---|---|
| `scenario_start`, `scenario_done` | explorer | scenario_id, title |
| `bug_observed` | explorer | uuid, scenario_id, title, symptom, page_url, screenshot_path |
| `bug_filed` | bug-filer | uuid, jira_key, dedup_target?, jira_url |
| `bug_dup_comment` | bug-filer | existing_key, comment_url |
| `scenario_proposed` | proposer | title, goal, parent_scenario_id |
| `subagent_start`, `subagent_end` | parsed from explorer stream-json | name, args, status |
| `note` | any | text |

### Two event channels (both needed)

1. **stream-json from `claude --output-format stream-json`** — gives the
   orchestrator visibility into the explorer's `Task` tool_use events so the
   TUI can render the nested sub-agent tree, and into assistant text for the
   log strip.
2. **Sentinel JSONL file** — the explorer is told in its system prompt to
   `Bash`-append structured events (bug_observed, scenario_proposed,
   bug_filed) to `$EXPLORER_EVENT_LOG`. The orchestrator tails it. This is the
   *canonical* source for queue + bug state because parsing English is
   unreliable.

### Dedup

In-memory dict `{title_signature: jira_key}` populated at startup from one
MCP search of the epic's existing issues, updated on every `bug_filed`. The
list is passed into every bug-filer Task prompt so the sub-agent can decide:
file new, or comment on existing.

`title_signature` is computed in `core/dedup.py` as the normalized title:
lowercase, strip punctuation, collapse whitespace, drop stopwords (`the`,
`a`, `an`, `on`, `in`, `to`, `for`, `with`, `is`, `are`). Two titles with
the same normalized form are treated as the same bug. This is intentionally
lossy and biases toward dedup; the bug-filer makes the final judgment using
the title list it's given (it can override and file new if symptoms differ).

## Component boundaries (Section 4)

```
explorer/
├── tui/
│   ├── app.py
│   ├── header.py
│   ├── sessions_pane.py
│   ├── bugs_pane.py
│   ├── log_strip.py
│   └── plan_screen.py
├── core/
│   ├── event_bus.py
│   ├── scenario_queue.py
│   ├── bug_store.py
│   ├── dedup.py
│   └── browser_lock.py
├── runner/
│   ├── claude_proc.py
│   ├── event_log_tailer.py
│   ├── planner.py
│   ├── explorer.py
│   └── prompts/
│       ├── system_planner.md
│       ├── system_explorer.md
│       ├── system_bug_filer.md
│       └── system_proposer.md
├── config/
│   ├── project_yaml.py
│   └── cli.py
└── __main__.py
```

Isolation rules:

- `tui/*` only reads from `EventBus` (or snapshots of `BugStore`/
  `ScenarioQueue`). Never spawns subprocesses, never calls Jira.
- `runner/*` only writes to `EventBus` and stdout. Never imports Textual.
- `core/*` is pure state — no I/O.
- Subprocess prompts live in `runner/prompts/` as markdown so they can be
  edited without touching Python.

### Boundary contract for explorer subprocesses

The explorer sees only:

- A short markdown system prompt with the scenario, the path to
  `$EXPLORER_EVENT_LOG`, and tool guidance (browser-harness recipes, when to
  Task into a bug-filer).
- The codebase (cwd).
- Tools: `Bash`, `Read`, `Grep`, `Glob`, `Write`, `Task`, `mcp__atlassian__*`.

The orchestrator does not know anything about exploring or filing logic —
that's all in markdown prompts.

## Error handling (Section 5)

| Failure | Detection | Response |
|---|---|---|
| Claude subprocess crashes mid-scenario | `Popen.wait()` non-zero before `scenario_done` | Mark scenario `failed`; TUI shows ✗; user can `r` to requeue. |
| browser-harness daemon hangs | Explorer Bash timeout | Counter is per-scenario (reset on `scenario_start`). Explorer bails after 3 consecutive harness failures in the same scenario, emits `note`; orchestrator banners. |
| Jira/MCP unavailable | bug-filer tool call fails | bug-filer writes `bug_filed_failed` with prepared body; orchestrator caches in `pending_bugs.jsonl`, retries every 60s. |
| Tab navigated away by user | Explorer screenshot URL mismatch | Explorer verifies URL at scenario start; if mismatch, emit `note` and skip. |
| Two bugs are the same | Dedup index hit | bug-filer adds a comment on existing issue, emits `bug_dup_comment`. |
| JSONL event log torn write | Parse fail per line | Tailer skips, logs `parse_error` to `events.jsonl`. |
| Orchestrator killed | n/a | `events.jsonl` + `bugs.json` preserved on disk; v1 leaves artifacts for human reading. Resume = v1.1 stretch. |

## Testing strategy

1. **Unit (pytest)** — `core/*` pure logic: queue transitions, dedup matching,
   event bus pub/sub, bug store ordering. Target: full branch coverage.
2. **Runner (pytest with fake subprocess)** — replace `subprocess.Popen` with
   a fixture emitting canned stream-json + JSONL. Assert `claude_proc.py`
   produces the right events. No real `claude` needed in CI.
3. **E2E smoke (manual)** — `tests/e2e/smoke.sh`: tiny canned HTML page served
   locally, a one-file FastAPI Jira mock, real `browser-harness`. Verifies
   plan approval, one bug filed, TUI doesn't crash. Run before each release.

TUI rendering isn't unit-tested — Textual snapshot tests are flaky for nested
reactive trees. Panes stay dumb (render from state) so unit tests of state
suffice.

## Open questions / explicit deferrals

- Resume mid-run (`--resume`) deferred to v1.1.
- Pre-flight Jira permission check (can we create + comment + attach?) — add
  a startup sanity call.
- Screenshot redaction (PII) — out of scope for v1; documented as a known
  hazard.
- Time/bug budgets — out of scope for v1; queue-empty is the only stop.

## Acceptance criteria

A v1 release is done when:

1. `explorer --jira-project … --epic … --codebase … --tab-url …` starts the
   TUI without errors.
2. The planner interviews the user, displays scenarios, and `y` approves.
3. Each scenario spawns one explorer that ends with either `scenario_done`
   or `failed`; both transitions render correctly in the sessions pane.
4. Filing a bug end-to-end against a live Jira sandbox produces a ticket
   under the named epic with: title, body containing scenario + symptom +
   suggested fix referencing real codebase files/lines, screenshot
   attachment.
5. A second observation matching an existing bug results in a comment on
   the existing issue, not a duplicate ticket.
6. The pending/discovered/bug counts in the header stay consistent with
   `events.jsonl` after a full run.
