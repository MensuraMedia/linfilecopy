"""Entry point: ``python3 -m linfilecopy [run <job> | list | preview <job>]``."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the headless CLI when a sub-command is given, otherwise start the GUI."""
    args = sys.argv[1:] if argv is None else argv
    from linfilecopy.cli import SUBCOMMANDS, main as cli_main

    if args and args[0] in SUBCOMMANDS:
        return cli_main(args)
    from linfilecopy.app import run_gui

    return run_gui(args)


if __name__ == "__main__":
    sys.exit(main())
