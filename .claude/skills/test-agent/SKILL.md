---
name: test-agent
description: This skill should be used when the user asks to "run tests", "test the app", "test the API", or wants automated tests run against the application.
version: 1.0.0
allowed-tools: Read, Bash, Write, Edit, Glob
user-invocable: true
---

# Test Agent — LinFileCopy

Run automated tests against LinFileCopy at `/home/user/projects/linfilecopy`.

## Test layout

| Suite | Command | Needs display |
|---|---|---|
| Model + engine unit tests | `python3 -m unittest discover -s tests -v` | no |
| rsync integration (real rsync on temp dirs) | included above (`tests/test_integration_*.py`) | no |
| UI smoke test (window builds, every page loads) | `xvfb-run -a python3 -m unittest tests.ui_smoke -v` | yes (Xvfb) |

## Responsibilities
1. Run the unit suite; report PASS/FAIL per test with a summary.
2. Check that every feature in `docs/CONCEPT.md` §6 has at least one golden test in `tests/test_rsync_builder.py` or a strategy test.
3. Run the UI smoke test under `xvfb-run` when UI files changed.
4. Never run tests against real user data: integration tests use `tempfile.TemporaryDirectory()` only.
