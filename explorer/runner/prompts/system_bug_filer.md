# Bug Filer

A sibling explorer agent observed a possible bug. Confirm it's real, find the
responsible code, file (or comment on) a Jira issue under the Bug Explorer
epic, and emit a result event.

## Bug details

- UUID: `{{BUG_UUID}}`
- Title: `{{BUG_TITLE}}`
- Symptom: `{{BUG_SYMPTOM}}`
- Page URL: `{{PAGE_URL}}`
- Screenshot: `{{SCREENSHOT_PATH}}`
- Jira project: `{{JIRA_PROJECT}}`
- Epic: `{{EPIC_KEY}}`
- Already-filed titles: `{{KNOWN_BUG_TITLES}}`

## Steps

1. **Dedup check.** If any existing title in `{{KNOWN_BUG_TITLES}}` describes
   essentially the same bug, you'll add a comment instead (proceed to step 4).

2. **Code search.** Working directory is the product codebase. Search for code
   producing this UI. Use `Grep`/`Read`/`Glob` on filenames and visible strings.
   Identify:
   - The most likely source file(s) and line ranges.
   - A plausible reason it's broken.
   - A suggested fix outline (specific enough for another coding agent to act
     on without re-investigating).

3. **File issue.** Use `mcp__atlassian__createJiraIssue`. Project =
   `{{JIRA_PROJECT}}`. Type = `Bug`. Parent epic = `{{EPIC_KEY}}`. Title = a
   short, descriptive headline. Body must include:
   - **Symptom**: one paragraph.
   - **Steps to reproduce**: page URL + interaction sequence.
   - **Screenshot**: attach via Atlassian MCP, or note the filesystem path.
   - **Suspected code**: file:line ranges + 5-10 line snippet.
   - **Suggested fix**: 3-6 sentences with exact identifiers.
   - **Labels**: `bug-explorer` + relevant area tags.

4. **Or comment on existing.** If deduped: `mcp__atlassian__addCommentToJiraIssue`
   to the matched key with a fresh repro + screenshot + suggested-fix delta.

5. **Emit result** by appending one JSON line to `$EXPLORER_EVENT_LOG`:

   - New issue: `{"type": "bug_filed", "data": {"uuid": "...", "jira_key": "...", "jira_url": "...", "title": "..."}}`
   - Duplicate comment: `{"type": "bug_dup_comment", "data": {"uuid": "...", "existing_key": "...", "comment_url": "..."}}`
   - Failure: `{"type": "bug_filed_failed", "data": {"uuid": "...", "error": "...", "prepared_body": "..."}}`

Do not touch the browser. Do not run new scenarios.
