---
paths:
  - "**/*"
---

# Token Hygiene Rules

## .claudeignore (Required for Every Project)
Every project MUST have a .claudeignore file excluding:
```
node_modules/
dist/
build/
*.log
coverage/
.env*
**/.git/
__pycache__/
*.pyc
.venv/
vendor/
```

## Context Management
1. Use /clear between unrelated tasks
2. Use sub-agents for heavy research tasks
3. Keep CLAUDE.md under 200 lines — use @imports for details
4. Use path-scoped rules to avoid loading irrelevant context
5. Reference docs with @path instead of pasting content inline
