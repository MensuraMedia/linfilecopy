"""rsync-compatible include/exclude matching in Python (#5, #13).

Used where the app walks folders itself (two-way sync scan, parallel bucket
split, filter Test button). Semantics follow ``man rsync`` FILTER RULES for
the patterns the UI can produce:

* first matching rule wins; no match means included;
* a leading ``/`` anchors the pattern at the transfer root;
* a trailing ``/`` matches directories only;
* a pattern with ``/`` or ``**`` in it is matched against the whole relative
  path (at any directory boundary unless anchored), otherwise only against
  the last path component;
* ``*`` matches within one component, ``**`` across components, ``?`` one
  character, ``[...]`` a character class; ``dir/***`` matches dir and all
  contents;
* an excluded directory hides everything inside it (callers prune the walk).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from linfilecopy.engine.rsync_builder import INTERNAL_EXCLUDES, PRESET_PATTERNS
from linfilecopy.model.enums import FilterAction
from linfilecopy.model.job import SyncJob


def _glob_to_regex(glob: str) -> str:
    out, i = [], 0
    while i < len(glob):
        c = glob[i]
        if c == "*":
            if glob[i:i + 3] == "***":
                out.append(".*")
                i += 3
                continue
            if glob[i:i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = glob.find("]", i + 1)
            if j < 0:
                out.append(re.escape(c))
            else:
                cls = glob[i + 1:j].replace("\\", "\\\\")
                if cls.startswith("!"):
                    cls = "^" + cls[1:]
                out.append(f"[{cls}]")
                i = j
        elif c == "\\" and i + 1 < len(glob):
            out.append(re.escape(glob[i + 1]))
            i += 1
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


@dataclass(frozen=True)
class Rule:
    include: bool
    pattern: str
    regex: re.Pattern[str]
    dir_only: bool
    full_path: bool
    anchored: bool

    @classmethod
    def compile(cls, include: bool, pattern: str) -> "Rule":
        p = pattern
        dir_only = p.endswith("/") and not p.endswith("***/")
        if dir_only:
            p = p.rstrip("/")
        anchored = p.startswith("/")
        if anchored:
            p = p.lstrip("/")
        full_path = anchored or "/" in p or "**" in p
        triple = p.endswith("/***")
        if triple:
            base = _glob_to_regex(p[:-4])
            body = f"{base}(?:/.*)?"
        else:
            body = _glob_to_regex(p)
        if full_path:
            regex = f"^{body}$" if anchored else f"^(?:.*/)?{body}$"
        else:
            regex = f"^{body}$"
        return cls(include, pattern, re.compile(regex, re.S), dir_only, full_path, anchored)

    def matches(self, rel_path: str, is_dir: bool) -> bool:
        if self.dir_only and not is_dir:
            return False
        subject = rel_path if self.full_path else rel_path.rsplit("/", 1)[-1]
        return bool(self.regex.match(subject))


class FilterMatcher:
    """Ordered rules; :meth:`excluded` answers for one relative path."""

    def __init__(self, rules: list[tuple[bool, str]]) -> None:
        self.rules = [Rule.compile(inc, pat) for inc, pat in rules if pat.strip()]

    @classmethod
    def for_job(cls, job: SyncJob, include_internal: bool = True) -> "FilterMatcher":
        rules: list[tuple[bool, str]] = [(r.action is FilterAction.INCLUDE, r.pattern.strip()) for r in job.filters.rules]
        for preset in job.filters.presets:
            rules += [(False, p) for p in PRESET_PATTERNS[preset]]
        if include_internal:
            rules += [(False, p) for p in INTERNAL_EXCLUDES] + [(False, ".lfc-partial/")]
        if job.filters.exclude_from:
            try:
                with open(job.filters.exclude_from, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        line = line.rstrip("\n")
                        if line and not line.startswith(("#", ";")):
                            if line.startswith("+ "):
                                rules.append((True, line[2:]))
                            elif line.startswith("- "):
                                rules.append((False, line[2:]))
                            else:
                                rules.append((False, line))
            except OSError:
                pass
        return cls(rules)

    def excluded(self, rel_path: str, is_dir: bool) -> bool:
        rel_path = rel_path.strip("/")
        for rule in self.rules:
            if rule.matches(rel_path, is_dir):
                return not rule.include
        return False
