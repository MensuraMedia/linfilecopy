"""Parallel rsync streams (#12).

rsync copies one file at a time. For fast storage (NVMe, arrays) several
rsync processes working on different top-level folders finish sooner. The
source's top-level entries are split into N buckets of similar total size
(largest first, greedy), each bucket becomes a ``--files-from`` list, and the
processes run concurrently. Mirror jobs get a final delete-only pass, because
``--delete`` inside a files-from run cannot see top-level extras.
"""
from __future__ import annotations

import os
import tempfile
import threading
from typing import TYPE_CHECKING

from linfilecopy.engine.filtermatch import FilterMatcher
from linfilecopy.i18n import _
from linfilecopy.model.enums import Mode

if TYPE_CHECKING:  # pragma: no cover
    from linfilecopy.engine.planner import Step
    from linfilecopy.engine.runner import JobRun


def tree_size(path: str, matcher: FilterMatcher, rel: str) -> int:
    """Bytes under ``path`` honouring the job's filters (apparent size)."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if not os.path.isdir(path) or os.path.islink(path):
        return st.st_size
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        base = os.path.relpath(dirpath, os.path.dirname(path))
        dirnames[:] = [d for d in dirnames if not matcher.excluded(f"{base}/{d}", True)]
        for f in filenames:
            if not matcher.excluded(f"{base}/{f}", False):
                try:
                    total += os.lstat(os.path.join(dirpath, f)).st_size
                except OSError:
                    pass
    return total


def split_buckets(sizes: dict[str, int], n: int) -> list[list[str]]:
    """Greedy balanced partition of entries into at most ``n`` non-empty buckets."""
    buckets: list[tuple[int, list[str]]] = [(0, []) for _ in range(max(1, n))]
    for name, size in sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0])):
        i = min(range(len(buckets)), key=lambda k: buckets[k][0])
        total, names = buckets[i]
        buckets[i] = (total + size, names + [name])
    return [sorted(names) for _, names in buckets if names]


def run_parallel(run: "JobRun", step: "Step") -> None:
    from linfilecopy.engine.runner import StepFailed

    source = step.params["source"]
    streams = int(step.params["streams"])
    matcher = FilterMatcher.for_job(run.job)
    run.step_description = _("Measuring folders to split the work…")
    run._notify(force=True)
    sizes: dict[str, int] = {}
    try:
        entries = sorted(os.listdir(source))
    except OSError as exc:
        raise StepFailed(_("Cannot read the source folder: {err}").format(err=exc.strerror), "") from exc
    for name in entries:
        run._check_cancel()
        full = os.path.join(source, name)
        if matcher.excluded(name, os.path.isdir(full) and not os.path.islink(full)):
            continue
        sizes[name] = tree_size(full, matcher, name)
    buckets = split_buckets(sizes, streams)
    run.snapshot.bytes_total_hint = sum(sizes.values())
    run.step_description = _("Copying with {n} parallel streams").format(n=len(buckets))
    run._notify(force=True)

    template = step.argv or []
    codes: dict[int, int] = {}
    with tempfile.TemporaryDirectory(prefix="lfc-par-") as tmp:
        threads = []
        for i, names in enumerate(buckets):
            list_path = os.path.join(tmp, f"bucket-{i}.txt")
            with open(list_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(names) + "\n")
            argv = [f"--files-from={list_path}" if a == "--files-from=<bucket>" else a for a in template]

            def worker(i: int = i, argv: list[str] = argv) -> None:
                codes[i] = run.run_rsync(argv, stream=i)

            t = threading.Thread(target=worker, name=f"lfc-par-{i}", daemon=True)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
    run._check_cancel()
    failed = {i: c for i, c in codes.items() if c not in (0, 24)}
    run.exit_code = max(codes.values(), default=0) if failed else (24 if 24 in codes.values() else 0)
    if failed:
        from linfilecopy.engine import exitcodes

        info = exitcodes.refine_with_stderr(exitcodes.explain(next(iter(failed.values()))), run.errors)
        raise StepFailed(info.message, info.fix, next(iter(failed.values())))

    if run.job.mode is Mode.MIRROR:
        run.step_description = _("Removing files that are no longer in the source")
        run._notify(force=True)
        argv = [a for a in template if not a.startswith("--files-from")]
        # Delete-only pass: --existing + --ignore-existing transfers nothing.
        rsync_at = next(i for i, a in enumerate(argv) if os.path.basename(a) == "rsync")
        argv = argv[: rsync_at + 1] + ["-r", "--existing", "--ignore-existing", "--delete-delay"] + [
            a for a in argv[rsync_at + 1:] if a.startswith(("--exclude", "--include", "--filter")) or a in (argv[-2], argv[-1])
        ]
        code = run.run_rsync(argv, stream=len(buckets))
        if code not in (0, 24):
            from linfilecopy.engine import exitcodes

            info = exitcodes.explain(code)
            raise StepFailed(info.message, info.fix, code)

