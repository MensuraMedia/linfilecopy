---
paths:
  - "**/*"
---

# Universal Memory Rules

## Session Memory Requirements
1. Claude MUST save a session log before ending any significant work session
2. Claude MUST update MEMORY.md when creating new memory files
3. Claude MUST capture user feedback (corrections AND confirmations) as memory
4. Claude MUST use absolute dates (YYYY-MM-DD), never relative dates
5. Claude MUST verify memory claims against current code before recommending actions

## Change Tracking Requirements
1. Every new feature MUST have a change manifest in memory/changes/
2. Every bug fix MUST capture the root cause in its change manifest
3. Every architectural decision MUST be recorded in memory/decisions.md
4. Change manifests MUST list all files affected

## Memory Hygiene
1. MEMORY.md index MUST stay under 200 lines
2. Memory files MUST have frontmatter (name, description, type)
3. Duplicate memories MUST be merged, not created
4. Stale memories MUST be updated or removed
5. Session logs older than 30 days SHOULD be archived

## Local Change Log Requirements (Additive — Does NOT Replace Git)
The local changelog is an additional layer that supplements git, not a replacement. Git commits and history remain the primary process for all code changes.
1. Every project MUST have a changelog.md in the project root or .claude/memory/
2. Every change MUST be logged with ISO 8601 datetime and brief description
3. The changelog is append-only — entries are NEVER deleted
4. The changelog MUST be updated as part of making the change, not after
5. If the changelog exceeds 500 entries, archive older entries to changelog-archive.md

## Recall Protocol
1. At session start, scan MEMORY.md for relevant context
2. Before making changes, check for related decisions and prior changes
3. When user asks about history, check session logs and change manifests
4. Always verify memory against current state before acting on it
