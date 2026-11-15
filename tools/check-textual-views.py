#!/usr/bin/env python3
"""Phase 6 Pure-VM contract check (Python Textual views).

Scans every ``examples/python/textual/*/src/*/views/**/*.py`` file (excluding
``views/adapter/**``) and verifies that widget classes only define methods
that are framework-allowed or thin pass-throughs into VM commands.

Spec reference: §6.1 Pure-VM contract — Textual widgets may compose layout
and forward Textual events into the bound VM, but they must not house any
business logic of their own.

Allow-list (per-method):

* ``__init__``, ``compose``, ``on_mount``, ``on_unmount``, ``render``,
  ``get_default_screen`` — framework lifecycle.
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

# Framework-controlled lifecycle hooks: statement counts are exempt (Textual
# decides when they run), but the hub rule still applies. get_default_screen
# is the App-level screen-installation hook (screens are installed, never
# composed — see NotesShowcaseApp).
LIFECYCLE_METHODS = {
    "__init__",
    "compose",
    "on_mount",
    "on_unmount",
    "render",
    "get_default_screen",
}


def _is_hub_name(name: str) -> bool:
    lowered = name.lower()
    return lowered == "hub" or lowered.endswith("_hub")


def _chain_has_hub(node: ast.expr, hub_locals: set[str]) -> bool:
    """Return True when the receiver chain of an expression reaches a hub.

    The chain is walked through attributes, call targets (``func``) and names.
    ``hub_locals`` holds local names that the method bound to a hub chain.
    """
    while True:
        if isinstance(node, ast.Attribute):
            if _is_hub_name(node.attr):
                return True
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Name):
            return _is_hub_name(node.id) or node.id in hub_locals
        else:
            return False


def _hub_locals(method: ast.AST) -> set[str]:
    """Return local names that a method binds to a hub chain.

    ``messages = self._vm.hub.messages`` makes ``messages`` a hub stream, so a
    later ``messages.subscribe(...)`` in the same method is a direct subscription.
    The search repeats until no new name is found, so an alias of an alias also
    counts.
    """
    assignments: list[tuple[list[ast.expr], ast.expr]] = []
    for node in ast.walk(method):
        if isinstance(node, ast.Assign):
            assignments.append((node.targets, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            assignments.append(([node.target], node.value))

    found: set[str] = set()
    changed = True
    while changed:
        changed = False
        for targets, value in assignments:
            if not _chain_has_hub(value, found):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in found:
                    found.add(target.id)
                    changed = True
    return found


def _hub_subscription_calls(method: ast.AST) -> list[ast.Call]:
    """Return every direct hub subscription call inside a method.

    Textual widgets bypass the adapter when they wire themselves to the
    message hub. A call counts when its ``subscribe`` receiver chain reaches a
    hub, wherever the call sits. This catches:

    * ``self._vm.hub.messages.subscribe(...)``, and the same call used as an argument
      or assignment value, such as ``self._subs.append(...)``
    * ``self._vm.hub.messages.pipe(f).subscribe(...)``
    * ``resolve_hub(self._vm).messages.subscribe(...)``
    * ``messages = self._vm.hub.messages`` followed by ``messages.subscribe(...)``
    """
    hub_locals = _hub_locals(method)
    calls: list[ast.Call] = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (
            isinstance(fn, ast.Attribute)
            and fn.attr == "subscribe"
            # Word-anchored match ("hub" / "*_hub"), not a substring — a bare
            # substring would flag e.g. `github.subscribe(...)`.
            and _chain_has_hub(fn.value, hub_locals)
        ):
            calls.append(node)
    return calls


# Compound statements whose inner statements count toward a handler's size.
_TRY_TYPES: tuple[type[ast.stmt], ...] = (
    (ast.Try, ast.TryStar) if hasattr(ast, "TryStar") else (ast.Try,)
)


def _nested_bodies(stmt: ast.stmt) -> list[list[ast.stmt]] | None:
    """Return the statement lists nested in a compound statement.

    Returns ``None`` for a simple statement.
    """
    if isinstance(stmt, ast.If | ast.For | ast.AsyncFor | ast.While):
        return [stmt.body, stmt.orelse]
    if isinstance(stmt, ast.With | ast.AsyncWith):
        return [stmt.body]
    if isinstance(stmt, _TRY_TYPES):
        handlers = [handler.body for handler in stmt.handlers]
        return [stmt.body, *handlers, stmt.orelse, stmt.finalbody]
    if isinstance(stmt, ast.Match):
        return [case.body for case in stmt.cases]
    return None


def _count_real_statements(body: list[ast.stmt]) -> int:
    """Return the effective thin-handler statement count.

    A compound statement (``if``, ``with``, ``for``, ``while``, ``try``,
    ``match``) counts the statements inside it, so a block cannot hide several
    statements behind one line. A guarded one-call handler such as
    ``if event.button.id: cmd.execute()`` still counts as one statement.
    """
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
        nested = _nested_bodies(stmt)
        if nested is None:
            count += 1
        else:
            count += max(1, sum(_count_real_statements(block) for block in nested))
    return count


def _hub_violations(path: Path, method: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Return one violation for each direct hub subscription in a method."""
    name = method.name
    return [
        f"{path}:{call.lineno}: '{name}' subscribes to the hub "
        f"directly (forbidden in views — use the adapter)"
        for call in _hub_subscription_calls(method)
    ]


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

            # Framework lifecycle — statement counts are exempt (the
            # framework controls when they run), but the hub rule still
            # applies: on_mount/__init__ are precisely where a forbidden
            # direct subscription would naturally be wired.
            if name in LIFECYCLE_METHODS:
                violations.extend(_hub_violations(path, item))
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
                violations.extend(_hub_violations(path, item))
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
