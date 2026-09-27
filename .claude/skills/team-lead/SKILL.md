---
name: team-lead
description: This skill should be used when the user asks to "review the project", "run all checks", "team review", "full review", "coordinate agents", or wants a comprehensive project review coordinating QA and testing.
version: 1.0.0
allowed-tools: Read, Bash, Grep, Glob, Write, Edit, Agent
user-invocable: true
---

# Team Lead — LinFileCopy

Coordinate quality assurance and testing workflows for LinFileCopy at `/home/user/projects/linfilecopy`.

## Role

The team lead orchestrates work between specialized agents and provides a consolidated project status report. It does not duplicate the work of other agents — it delegates, collects results, and reports.

## Workflow

### Step 1: Project Status Assessment

Before delegating, perform a quick assessment:

- Check git status for uncommitted changes
- Verify the app starts/builds cleanly
- Count key project metrics (files, lines, data counts)
- Check if the app is currently running

### Step 2: Delegate to Agents

Launch the following agents in parallel:

1. **QA Agent** (`/qa-agent`) — Code quality, data integrity, route verification
2. **Test Agent** (`/test-agent`) — Unit tests, integration tests, smoke tests (skip slow tests unless user requested)

### Step 3: Consolidated Report

After agents complete, compile a single report:

```
## Project Status
- Git: [clean/dirty, branch, last commit]
- App: [running/stopped, build status]
- Stats: [key project metrics]

## QA Results
[Summary from QA agent — pass/fail counts, any issues]

## Test Results
[Summary from Test agent — pass/fail counts, any failures]

## Action Items
[Prioritized list of issues to fix, if any]

## Recommendation
[Ship / fix issues first / needs review]
```

### Step 4: Fix Coordination (if needed)

If issues are found:
1. Prioritize by severity (security > data corruption > broken functionality > code quality)
2. Apply fixes directly for clear-cut issues
3. Flag ambiguous issues for user decision
4. Re-run the failing checks after fixes to confirm resolution
5. Commit fixes if all checks pass
