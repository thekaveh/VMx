#!/usr/bin/env python3
"""Phase 6 Pure-VM contract check (C# Avalonia code-behind).

Scans every ``examples/csharp/avalonia/*/Views/**/*.axaml.cs`` file (excluding
``Views/Adapter/``) and asserts each constructor / method body contains only
an ``InitializeComponent()`` or ``AvaloniaXamlLoader.Load(this)`` call.

Spec reference: §6.1 Pure-VM contract — view code-behind may load the XAML
and nothing else; every binding, command, and selection routes through the
VM exposed as ``DataContext``.

Why both forms are allowed:

* ``InitializeComponent()`` — historical Avalonia source-generator entry point.
* ``AvaloniaXamlLoader.Load(this)`` — the explicit loader the Phase 5.a /
  retrofit code-behind files use (no source generator in this showcase).

Either keeps the view file body trivial. Anything else (a field assignment, a
``this.AttachDevTools()`` call, an event subscription) is rejected.

A view is a partial class, so its members can also sit in another file. For each
view, every other ``.cs`` file of the same app project that declares
``partial class <Name>`` is checked the same way. ``bin/``, ``obj/`` and
``Views/Adapter/`` are not scanned.

The script is also tolerant of *expression-bodied* constructors, e.g.
``public MyView() => AvaloniaXamlLoader.Load(this);`` — which is the form
used throughout the Phase 5.a + retrofit code-behind. The regex strips the
``=>`` body and the brace body equally and checks the inner statement against
the allow-list.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EXEMPT_RE = re.compile(r"[/\\]Views[/\\]Adapter[/\\]")

# Accept either form, optionally with `this.` qualifier on InitializeComponent.
_ALLOWED_STMT = re.compile(
    r"^\s*(?:this\.)?(?:InitializeComponent\(\)|AvaloniaXamlLoader\.Load\(this\))\s*;?\s*$"
)


def _strip_comments_and_strings(src: str) -> str:
    """Remove ``// line``, ``/* block */`` comments and string contents so the
    statement-allow-list isn't confused by literal text or example comments.

    Strings are replaced with empty quotes to preserve token boundaries.
    """
    # /* ... */ block comments (non-greedy, multiline)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    # // line comments
    src = re.sub(r"//[^\n]*", "", src)
    # "..." string literals (no escapes that span newlines in the showcase)
    src = re.sub(r'"(?:[^"\\]|\\.)*"', '""', src)
    # verbatim @"..."
    src = re.sub(r'@"[^"]*"', '""', src)
    return src


# Matches an expression-bodied member declaration, e.g.
#   `public MyView() => AvaloniaXamlLoader.Load(this);`
# Captures the right-hand call so we can validate it against _ALLOWED_STMT.
_EXPR_BODIED_MEMBER = re.compile(
    r"(?:public|private|internal|protected|static|partial|sealed|override|virtual|\s)+"
    # Method (`Name(args)`) OR property (`Name`) — an expression-bodied
    # property previously slipped past both this regex and the leaf-brace
    # scan (its body sits in a non-leaf brace region).
    r"[A-Za-z0-9_<>]+(?:\s*\([^)]*\))?\s*=>\s*([^;{}]+);"
)


def check(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    src = _strip_comments_and_strings(raw)
    violations: list[str] = []

    # First, validate every expression-bodied method/ctor declaration and then
    # *remove* it from the source so the brace-body scan doesn't see it again
    # as a stray line inside the surrounding class body.
    def _validate_expr(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        stmt = expr + ";"
        if not _ALLOWED_STMT.match(stmt):
            violations.append(f"{path}: disallowed expression-bodied member: => {expr};")
        return ""  # strip from source

    src_after_expr = _EXPR_BODIED_MEMBER.sub(_validate_expr, src)

    # Find every brace-delimited body (method or constructor bodies). The
    # showcase's view code-behind has no nested braces inside method bodies,
    # so a non-greedy `\{[^{}]*\}` match catches each leaf body cleanly. Strip
    # each validated body afterward so a second pass can inspect class-level
    # statements that live in non-leaf braces.
    def _validate_body(match: re.Match[str]) -> str:
        body = match.group(1)
        for line in body.splitlines():
            stmt = line.strip()
            if not stmt:
                continue
            if not _ALLOWED_STMT.match(stmt):
                violations.append(f"{path}: disallowed statement in code-behind body: {stmt}")
        return "{}"

    src_after_bodies = re.sub(r"\{([^{}]*)\}", _validate_body, src_after_expr)

    for line in src_after_bodies.splitlines():
        stmt = line.strip()
        if not stmt or stmt in {"{", "}"}:
            continue
        if (
            stmt.startswith("using ")
            or stmt.startswith("namespace ")
            or stmt.startswith("[")
            or " class " in f" {stmt} "
            or stmt.endswith("{")
        ):
            continue
        if ";" in stmt:
            violations.append(f"{path}: disallowed class-level code-behind statement: {stmt}")

    return violations


AVALONIA_ROOT = Path("examples") / "csharp" / "avalonia"
CODE_BEHIND_SUFFIX = ".axaml.cs"
_PARTIAL_CLASS_RE = re.compile(r"\bpartial\s+class\s+(\w+)")
_BUILD_DIRS = {"bin", "obj"}


def _app_dir(view: Path, root: Path) -> Path:
    """Return the app project directory that holds a view (the `*` in the scan glob)."""
    return root / AVALONIA_ROOT / view.relative_to(root / AVALONIA_ROOT).parts[0]


def _view_class_name(view: Path) -> str:
    """Return the class a view file declares, or the file stem when none is found."""
    match = _PARTIAL_CLASS_RE.search(view.read_text(encoding="utf-8"))
    if match is not None:
        return match.group(1)
    return view.name[: -len(CODE_BEHIND_SUFFIX)]


def _partial_files(app_dir: Path, class_name: str) -> list[Path]:
    """Return the other .cs files of an app project that declare `partial class <name>`.

    Build output (`bin/`, `obj/`) and the adapter sub-layer (`Views/Adapter/`)
    are not scanned.
    """
    declares = re.compile(rf"\bpartial\s+class\s+{re.escape(class_name)}\b")
    found: list[Path] = []
    for path in sorted(app_dir.rglob("*.cs")):
        rel = path.relative_to(app_dir).parts
        if any(part in _BUILD_DIRS for part in rel) or rel[:2] == ("Views", "Adapter"):
            continue
        if declares.search(path.read_text(encoding="utf-8")):
            found.append(path)
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repo root (default: current dir)")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    targets = [
        p
        for p in root.glob("examples/csharp/avalonia/*/Views/**/*.axaml.cs")
        if not EXEMPT_RE.search(str(p))
    ]

    failures: list[str] = []
    scanned: set[Path] = set(targets)
    for p in targets:
        failures.extend(check(p))
        # The view is a partial class, so its members can sit in another file of the project.
        for partial in _partial_files(_app_dir(p, root), _view_class_name(p)):
            if partial not in scanned:
                scanned.add(partial)
                failures.extend(check(partial))

    if failures:
        print("\n".join(failures), file=sys.stderr)
        print(
            f"\n[FAIL] {len(failures)} violation(s) across {len(targets)} files",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] {len(targets)} axaml.cs files clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
