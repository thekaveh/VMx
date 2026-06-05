#!/usr/bin/env python3
"""Phase 6 Pure-VM contract check (Python Textual views).

Scans every ``examples/python/textual/*/src/*/views/**/*.py`` file (excluding
``views/adapter/**``) and verifies that widget classes only define methods
that are framework-allowed or thin pass-throughs into VM commands.

Spec reference: §6.1 Pure-VM contract — Textual widgets may compose layout
and forward Textual events into the bound VM, but they must not house any
business logic of their own.

Allow-list (per-method):

* ``__init__``, ``compose``, ``on_mount``, ``render`` — framework lifecycle.
* ``action_<name>`` — Textual key-binding actions. Body must be ≤ 1
  non-``pass`` statement so the heavy lifting lives in the bound command.
* ``on_<event>`` — Textual event handlers (``on_button_pressed``,
  ``on_tree_node_selected``, ``on_input_changed``, …). Permitted but kept
  thin: body must be ≤ 1 statement (single expression-call or a guarded
  expression). They MUST NOT subscribe to the hub directly — that's the
  adapter's job.

Anything else (e.g. a custom ``def save_note(self)`` business method, a
``def on_message(self)`` hub subscription) is rejected as a Pure-VM
violation.

The script also flags module-level helper functions only when they live
inside a widget class body; module-level helpers (outside classes) are
allowed and are used by the showcase widgets to keep their bodies thin.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

LIFECYCLE_METHODS = {"__init__", "compose", "on_mount", "render"}


def _is_hub_subscription(node: ast.stmt) -> bool:
    """Return True when the statement looks like a direct hub subscription.

    Textual widgets bypass the adapter when they wire themselves to the
    message hub. This catches:

    * ``self._vm.hub.messages.subscribe(...)``
    * ``hub.subscribe(...)``
    """
    if not isinstance(node, ast.Expr):
        return False
    call = node.value
    if not isinstance(call, ast.Call):
        return False
    fn = call.func
    while isinstance(fn, ast.Attribute):
        if fn.attr == "subscribe":
            # Walk back to see whether 'hub' appears in the attribute chain.
            walk = fn
            while isinstance(walk, ast.Attribute):
                if walk.attr == "hub" or (
                    isinstance(walk.value, ast.Name) and walk.value.id.lower() == "hub"
                ):
                    return True
                walk = walk.value  # type: ignore[assignment]
            return False
        fn = fn.value  # type: ignore[assignment]
    return False


def _count_real_statements(body: list[ast.stmt]) -> int:
    """Return the number of statements that aren't ``pass`` or a bare docstring."""
    count = 0
    for i, stmt in enumerate(body):
        if isinstance(stmt, ast.Pass):
            continue
        # Skip a leading docstring (first stmt that is a bare Constant string).
        if (
            i == 0
            and isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            continue
        count += 1
    return count


def check_module(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: syntax error: {exc}"]

    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            name = item.name

            # Framework lifecycle — accept as-is (the framework controls when
            # they run; their statement count is irrelevant to Pure-VM).
            if name in LIFECYCLE_METHODS:
                continue

            real_stmts = _count_real_statements(item.body)

            if name.startswith("action_"):
                if real_stmts > 1:
                    violations.append(
                        f"{path}:{item.lineno}: '{name}' has {real_stmts} statements "
                        f"(max 1 for action_*)"
                    )
                continue

            if name.startswith("on_"):
                # Event handler — must be thin and must not subscribe to the
                # hub directly.
                if real_stmts > 1:
                    violations.append(
                        f"{path}:{item.lineno}: '{name}' has {real_stmts} statements "
                        f"(max 1 for on_* event handlers)"
                    )
                for stmt in item.body:
                    if _is_hub_subscription(stmt):
                        violations.append(
                            f"{path}:{item.lineno}: '{name}' subscribes to the hub "
                            f"directly (forbidden in views — use the adapter)"
                        )
                continue

            violations.append(
                f"{path}:{item.lineno}: disallowed method '{name}' in widget class "
                f"'{node.name}' (Pure-VM contract: only __init__/compose/on_mount/"
                f"render/action_*/on_* permitted)"
            )

    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repo root (default: current dir)")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    targets = [
        p
        for p in root.glob("examples/python/textual/*/src/*/views/**/*.py")
        if "adapter" not in p.parts
    ]

    failures: list[str] = []
    for p in targets:
        failures.extend(check_module(p))

    if failures:
        print("\n".join(failures), file=sys.stderr)
        print(
            f"\n[FAIL] {len(failures)} violation(s) across {len(targets)} files",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] {len(targets)} Textual view modules clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
