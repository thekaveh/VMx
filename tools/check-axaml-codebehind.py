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
    r"[A-Za-z0-9_<>]+\s*\([^)]*\)\s*=>\s*([^;{}]+);"
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
            violations.append(
                f"{path}: disallowed expression-bodied member: => {expr};"
            )
        return ""  # strip from source

    src_after_expr = _EXPR_BODIED_MEMBER.sub(_validate_expr, src)

    # Find every brace-delimited body (method or constructor bodies). The
    # showcase's view code-behind has no nested braces inside method bodies,
    # so a non-greedy `\{[^{}]*\}` match catches each leaf body cleanly.
    for body in re.findall(r"\{([^{}]*)\}", src_after_expr):
        for line in body.splitlines():
            stmt = line.strip()
            if not stmt:
                continue
            if not _ALLOWED_STMT.match(stmt):
                violations.append(
                    f"{path}: disallowed statement in code-behind body: {stmt}"
                )

    return violations


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
    for p in targets:
        failures.extend(check(p))

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
