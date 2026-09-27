---
paths:
  - "**/*"
---

# Universal Security Rules

1. NEVER log, commit, or store secrets (.env, API keys, tokens, passwords)
2. NEVER commit .env files — always .gitignore them
3. Validate all external input at system boundaries
4. Use parameterized queries for database access (no string concatenation)
5. Sanitize output to prevent XSS
6. Follow OWASP Top 10 guidelines
7. Review dependencies for known vulnerabilities before adding
8. Use least-privilege principles for file/network access

## LinFileCopy-specific (Python / GTK / rsync)
9. NEVER build shell strings: always pass argv lists to `subprocess` (`shell=False`). Use `shlex.join` only for the *display* preview.
10. Validate every user path before use: must be absolute, must exist (source), must not be `/` or a system directory as a Mirror/Two-way destination.
11. Drive passphrases are held in memory only for the unlock call, or stored in libsecret when the user opts in. Never in job JSON, logs, history or argv.
12. Treat filenames as untrusted: escape with `GLib.markup_escape_text` before putting them in Pango markup.
13. sqlite access uses parameterised queries only.
14. Generated systemd units / crontab lines quote job ids (ids are restricted to `[a-z0-9-]`).
