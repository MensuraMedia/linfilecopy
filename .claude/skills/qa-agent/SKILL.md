---
name: qa-agent
description: This skill should be used when the user asks to "run QA", "quality check", "review code quality", "check the app", or wants a quality assurance review of the application.
version: 1.0.0
allowed-tools: Read, Bash, Grep, Glob
user-invocable: true
---

# QA Agent — LinFileCopy

Perform quality assurance checks on LinFileCopy at `/home/user/projects/linfilecopy`.

## Responsibilities

### 1. Code quality
- Unused imports / dead code (`python3 -m pyflakes` if available, else manual)
- Type hints and docstrings on public functions
- `model/` and `engine/` never import Gtk (`grep -rn "Gtk" linfilecopy/model linfilecopy/engine` must be empty)
- No `shell=True`, no string-built commands
- All user-visible strings wrapped in `_()`

### 2. Build philosophy
- No runtime dependency outside stdlib + PyGObject (check imports)
- No network code paths (no `urllib`, `http`, `socket`, `ssh`, `rclone`)
- Every icon used in `linfilecopy/ui` exists in `tools/icons.manifest` and in `linfilecopy/data/icons/`

### 3. Data integrity
- Templates in `linfilecopy/data/templates/*.json` load via `SyncJob.from_dict` without error
- Job JSON round-trips losslessly

### 4. Responsiveness
- No blocking calls (`subprocess.run`, `time.sleep`, file walks) in UI callbacks

## Output
PASS/FAIL checklist with file:line for failures and a summary count.
