#!/usr/bin/env python3
"""Fail if any function both calls _() and binds the name _ locally.

Binding ``_`` anywhere in a function (``_ = x``, ``for _ in``, ``a, _ = f()``)
makes it local for the whole function, so an earlier ``_("text")`` raises
UnboundLocalError at runtime. Comprehensions have their own scope and are fine.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


def binds_underscore(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.Lambda)):
            continue
        if isinstance(sub, ast.Name) and sub.id == "_" and isinstance(sub.ctx, ast.Store):
            return True
    return False


def own_nodes(func: ast.AST):  # type: ignore[no-untyped-def]
    """Nodes of this function, not of nested functions or comprehensions."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ListComp, ast.SetComp,
                          ast.DictComp, ast.GeneratorExp, ast.ClassDef)):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


def main() -> int:
    bad = []
    for path in Path(sys.argv[1] if len(sys.argv) > 1 else "linfilecopy").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nodes = list(own_nodes(func))
            stores = any(isinstance(n, ast.Name) and n.id == "_" and isinstance(n.ctx, ast.Store) for n in nodes)
            calls = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_" for n in ast.walk(func))
            if stores and calls:
                bad.append(f"{path}:{func.lineno} {func.name}")
    for b in bad:
        print("binds _ and calls _():", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
