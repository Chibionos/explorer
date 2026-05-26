# Confluence Writer

A scenario just finished. Append a section to a Confluence page documenting
what was tested, what was found, and where the evidence lives.

## Inputs

- Confluence page ID: `{{CONFLUENCE_PAGE_ID}}`
- Scenario ID: `{{SCENARIO_ID}}`
- Scenario title: `{{SCENARIO_TITLE}}`
- Scenario goal: `{{SCENARIO_GOAL}}`
- Scenario status: `{{SCENARIO_STATUS}}`   (one of: done, failed, aborted)
- Bugs filed during this scenario: `{{BUGS_FILED}}`
  (a comma-separated list of "AE-1234 — title" entries; may be empty)
- Screenshots collected: `{{SCREENSHOT_PATHS}}`
  (newline-separated absolute filesystem paths in the run directory)
- Run directory: `{{RUN_DIR}}`
- Tab URL tested: `{{TAB_URL}}`

## What to do

1. Read the current Confluence page with `mcp__atlassian__getConfluencePage`
   (pageId=`{{CONFLUENCE_PAGE_ID}}`, contentFormat="markdown"). Hold onto its
   current body.

2. Build a new markdown section for this scenario. Template:

   ```
   ## {{SCENARIO_TITLE}}

   - **ID**: `{{SCENARIO_ID}}`
   - **Status**: {{SCENARIO_STATUS}}
   - **Tab tested**: `{{TAB_URL}}`
   - **When**: <ISO timestamp, use `date -Iseconds` from Bash>

   **Goal**

   {{SCENARIO_GOAL}}

   **Bugs filed**

   - <one bullet per bug, formatted as: AE-1234 — title (link to https://uipath.atlassian.net/browse/AE-1234)>
   - (or "_none_" if no bugs were filed in this scenario)

   **Evidence**

   Screenshots captured during this scenario (filesystem paths in the run
   directory `{{RUN_DIR}}`):

   - <one bullet per screenshot path>

   ---
   ```

3. Update the page with `mcp__atlassian__updateConfluencePage` using
   pageId=`{{CONFLUENCE_PAGE_ID}}`, contentFormat="markdown", and a new body
   equal to **the existing body** + the new section appended at the end.
   (Don't replace the existing body — append.)

4. After a successful update, emit ONE JSON line to `$EXPLORER_EVENT_LOG`:

   ```
   {"type": "confluence_updated", "data": {"page_id": "{{CONFLUENCE_PAGE_ID}}", "scenario_id": "{{SCENARIO_ID}}"}}
   ```

   Or on failure:

   ```
   {"type": "confluence_update_failed", "data": {"scenario_id": "{{SCENARIO_ID}}", "error": "<short message>"}}
   ```

Do NOT touch the browser. Do NOT file bugs. Do NOT propose new scenarios.
Read → append → write → emit → exit.
