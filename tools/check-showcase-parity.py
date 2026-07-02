#!/usr/bin/env python3
"""Phase 6 cross-flavor parity check.

Verifies that each notes-showcase flavor ships the same canonical set of
VM-level test files, so the README parity matrix is backed by actual code.
It also verifies that every flagship example suite carries the five normative
THEME scenario IDs.

Expected slugs (each must have a matching test file in each flavor):

    workspace_vm, notebooks_root_vm, notebook_vm,
    notes_view_vm, note_vm, note_form_vm,
    status_bar_vm, notifications_vm, capability_actions_vm,
    theme_vm, in_memory_repository

Per-flavor naming conventions:

* C# — ``NotesShowcase.Tests/ViewModels/<PascalSlug>Tests.cs``
  (and ``Models/InMemoryNoteRepositoryTests.cs`` for the repo slug).
* Python — ``notes_showcase/tests/viewmodels/test_<slug>.py``
  (and ``tests/models/test_in_memory_repository.py``).
* TypeScript — ``notes-showcase/tests/viewmodels/<camelSlug>.test.ts(x)``
  (and ``tests/models/inMemoryRepository.test.ts``).
* Swift — ``notes-showcase/Tests/NotesShowcaseTests/<PascalSlug>Tests.swift``
  (and ``InMemoryNoteRepositoryTests.swift`` for the repo slug).

The matcher is name-only: it searches each flavor's test root recursively for
a file whose basename matches the slug under any of the accepted conventions.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EXPECTED = [
    "workspace_vm",
    "notebooks_root_vm",
    "notebook_vm",
    "notes_view_vm",
    "note_vm",
    "note_form_vm",
    "status_bar_vm",
    "notifications_vm",
    "capability_actions_vm",
    "theme_vm",
    "in_memory_repository",
]

ROOTS = {
    "csharp": Path("examples/csharp/avalonia/NotesShowcase.Tests"),
    "python": Path("examples/python/textual/notes_showcase/tests"),
    "typescript": Path("examples/typescript/react/notes-showcase/tests"),
    "swift": Path("examples/swift/notes-showcase/Tests"),
}

THEME_IDS = [f"THEME-{i:03d}" for i in range(1, 6)]


def _pascal(snake: str) -> str:
    return "".join(p.capitalize() for p in snake.split("_"))


def _camel(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _file_stems(root: Path, patterns: list[str]) -> set[str]:
    stems: set[str] = set()
    if not root.exists():
        return stems
    for pat in patterns:
        for p in root.rglob(pat):
            stems.add(p.stem.lower())
    return stems


# Per-flavor synonyms for slugs that don't translate verbatim. Each entry maps
# a canonical slug to a list of *additional* PascalCase / camelCase / snake_case
# fragments accepted in the matching file's stem.
SLUG_SYNONYMS: dict[str, list[str]] = {
    # The C# project named its repo test "InMemoryNoteRepository" — same
    # fixture, sharper-noun naming. Accept both spellings everywhere.
    "in_memory_repository": ["in_memory_note_repository", "inmemorynoterepository"],
}


def _expected_keys(flavor: str, slug: str) -> list[str]:
    """Return acceptable file-stem fragments for ``slug`` in ``flavor``.

    Match is a *substring* check against the file stem (case-insensitive), so
    "<canonical>tests" works for both ``InMemoryRepositoryTests.cs`` (exact)
    and ``InMemoryNoteRepositoryTests.cs`` (matches via the synonym list).
    """
    candidates = [slug, *SLUG_SYNONYMS.get(slug, [])]
    keys: list[str] = []
    for s in candidates:
        pascal = _pascal(s)
        camel = _camel(s)
        if flavor in ("csharp", "swift"):
            # Both use `<Pascal>Tests` file stems (`…Tests.cs` / `…Tests.swift`).
            keys.append(f"{pascal}Tests".lower())
        elif flavor == "python":
            keys.append(f"test_{s}".lower())
        else:  # typescript
            # Stem of `foo.test.ts` is `foo.test` — match on the `<camel>.test` prefix.
            keys.append(f"{camel}.test".lower())
    return keys


def _stem_contains(stem: str, key: str) -> bool:
    return key in stem


def _theme_marker_present(flavor: str, theme_id: str, text: str) -> bool:
    """Return true when ``theme_id`` appears on an executable test declaration."""
    number = theme_id.split("-", 1)[1]
    compact = f"THEME{number}"
    underscored = f"THEME_{number}"
    suffix = r"(?:\b|_)"
    escaped = re.escape(theme_id)

    if flavor == "python":
        return (
            re.search(rf"@pytest\.mark\.conformance\(\s*['\"]{escaped}['\"]\s*\)", text) is not None
            or re.search(rf"def\s+test_{underscored}{suffix}", text) is not None
        )
    if flavor == "csharp":
        return (
            re.search(rf"\[Fact[^\]]*\]\s*public\s+void\s+{underscored}{suffix}", text) is not None
        )
    if flavor == "typescript":
        return (
            re.search(rf"\bdescribe\(\s*['\"]{escaped}\b", text) is not None
            or re.search(rf"\bit\(\s*['\"]{escaped}\b", text) is not None
        )
    if flavor == "swift":
        return re.search(rf"\bfunc\s+test{compact}{suffix}", text) is not None
    return False


def check(roots: dict[str, Path]) -> int:
    failed = False
    for flavor, root in roots.items():
        if flavor == "csharp":
            stems = _file_stems(root, ["*Tests.cs"])
        elif flavor == "swift":
            stems = _file_stems(root, ["*Tests.swift"])
        elif flavor == "python":
            stems = _file_stems(root, ["test_*.py"])
        else:  # typescript
            stems = _file_stems(root, ["*.test.ts", "*.test.tsx"])

        if not stems and not root.exists():
            print(f"{flavor}: test root not found: {root}", file=sys.stderr)
            failed = True
            continue

        for slug in EXPECTED:
            keys = _expected_keys(flavor, slug)
            if not any(_stem_contains(stem, k) for stem in stems for k in keys):
                print(
                    f"{flavor}: missing test for '{slug}' (expected stem matching one of {keys})",
                    file=sys.stderr,
                )
                failed = True

        text = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in {".cs", ".py", ".ts", ".tsx", ".swift"}
        )
        for theme_id in THEME_IDS:
            if not _theme_marker_present(flavor, theme_id, text):
                print(
                    f"{flavor}: missing executable scenario marker '{theme_id}'",
                    file=sys.stderr,
                )
                failed = True

    if failed:
        print("\n[FAIL] parity violations — see above", file=sys.stderr)
        return 1
    print(f"[OK] cross-flavor parity: {len(EXPECTED)} slugs x 4 flavors")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repo root (default: current dir)")
    args = ap.parse_args()
    # Resolve flavor roots against the repo root. ROOTS holds repo-relative
    # subpaths and is never mutated, so main() is safe to call repeatedly.
    repo_root = Path(args.root).resolve()
    roots = {f: repo_root / r for f, r in ROOTS.items()}
    return check(roots)


if __name__ == "__main__":
    sys.exit(main())
