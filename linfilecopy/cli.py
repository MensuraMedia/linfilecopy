"""Headless command line (used by the scheduler). Filled in during P7."""
from __future__ import annotations

SUBCOMMANDS = ("run", "list", "preview", "validate")


def main(argv: list[str]) -> int:
    print("headless commands are not implemented yet")
    return 2
