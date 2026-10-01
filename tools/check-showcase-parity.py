#!/usr/bin/env python3
"""Phase 6 cross-flavor parity check.

Verifies that each notes-showcase flavor ships the same canonical set of
VM-level test files, so the README parity matrix is backed by actual code.
It also verifies that every flagship example suite carries the five normative
THEME scenario IDs. Rust's Ratatui showcase is a reduced companion rather than
a fifth flagship; the check requires its exclusions to remain explicit in the
canonical Rust guide so omission cannot be mistaken for parity.

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
These are **structural** diagnostics: they prove that tests exist, not what
they assert.

The **behavioral** check covers two shared scenarios whose expected semantic
outcome every full showcase asserts through its own adapter
(``SharedScenarioTests.cs``, ``test_shared_scenario.py``,
``sharedScenario.test.ts``, ``SharedScenarioTests.swift``):

* ``examples/notes-showcase-scenario.json`` -- one bounded workspace lifecycle;
* ``examples/notes-showcase-theme-scenario.json`` -- the five THEME scenarios
  run in order against one ThemeVM.

This tool validates both definitions and requires each adapter to load both
files; the adapters' own test runs compare the outcome and fail with the
scenario, flavor, step, and differing value.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

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
SCENARIO = Path("examples/notes-showcase-scenario.json")
THEME_SCENARIO = Path("examples/notes-showcase-theme-scenario.json")
SCENARIO_ADAPTERS = {
    "csharp": "SharedScenarioTests.cs",
    "python": "test_shared_scenario.py",
    "typescript": "sharedScenario.test.ts",
    "swift": "SharedScenarioTests.swift",
}
SCENARIO_ACTIONS = (
    "construct",
    "create_note",
    "select_note",
    "edit_title",
    "save",
    "delete_selected_declined",
    "set_theme",
    "dispose",
)
THEME_SCENARIO_ACTIONS = (
    "construct",
    "set_theme",
    "set_accent",
    "toggle_high_contrast",
    "set_font_scale",
    "follow_system",
    "dispose",
)
RUST_SCOPE_DOC = Path("docs/content/examples/rust-tui-notes-showcase.md")
RUST_SCOPE_TERMS = (
    "reduced companion",
    "THEME-001..005",
    "IDialogService",
    "capability action bar",
    "async dispatcher scenario",
    "tag autocomplete",
)


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
    print(
        f"[OK] structural parity: {len(EXPECTED)} test-file slugs and "
        f"{THEME_IDS[0]}..{THEME_IDS[-1][-3:]} markers x 4 flavors (names and markers only)"
    )
    return 0


def check_rust_scope(repo_root: Path) -> int:
    scope_doc = repo_root / RUST_SCOPE_DOC
    if not scope_doc.is_file():
        print(f"rust: scope document not found: {scope_doc}", file=sys.stderr)
        return 1
    text = " ".join(scope_doc.read_text(encoding="utf-8").split())
    missing = [term for term in RUST_SCOPE_TERMS if term not in text]
    if missing:
        print(
            f"rust: reduced-companion scope is missing terms: {missing}",
            file=sys.stderr,
        )
        return 1
    print("[OK] Rust reduced-companion exclusions are documented")
    return 0


def _structure_problems(scenario: object) -> list[str]:
    """What keeps a scenario's steps from being read at all."""
    if not isinstance(scenario, dict) or not scenario.get("id"):
        return ["the scenario has no id"]
    steps = scenario.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["the scenario has no steps"]
    return [
        f"step {number} needs an action and an expect object"
        for number, step in enumerate(steps, start=1)
        if not isinstance(step, dict)
        or "action" not in step
        or not isinstance(step.get("expect"), dict)
    ]


def _common_problems(scenario: dict[str, Any], actions: tuple[str, ...]) -> list[str]:
    """Coverage every shared scenario needs: its actions, an error path, a teardown."""
    steps = scenario["steps"]
    problems = []
    if not scenario.get("normalization"):
        problems.append("the scenario lists no normalization rules")
    exercised = [step["action"] for step in steps]
    missing = [action for action in actions if action not in exercised]
    if missing:
        problems.append(f"no step exercises {missing}")
    if not any(step["expect"].get("error") == "invalid" for step in steps):
        problems.append("no step expects a rejected operation (error path)")
    last = steps[-1]
    if last["action"] != "dispose" or last["expect"].get("disposed") is not True:
        problems.append("the scenario does not end with an asserted teardown")
    return problems


def _scenario_problems(scenario: object) -> list[str]:
    """What keeps the lifecycle scenario from covering the required behavior."""
    problems = _structure_problems(scenario)
    if problems or not isinstance(scenario, dict):
        return problems
    problems = _common_problems(scenario, SCENARIO_ACTIONS)
    steps = scenario["steps"]
    if len({step.get("index") for step in steps if step["action"] == "select_note"}) < 2:
        problems.append("the selection never changes between two notes")
    live = [step for step in steps if step["action"] != "dispose"]
    if not all(isinstance(step["expect"].get("notes"), list) for step in live):
        problems.append("a step before dispose does not assert the notes order")
    return problems


def _theme_scenario_problems(scenario: object) -> list[str]:
    """What keeps the THEME scenario from covering THEME-001..005."""
    problems = _structure_problems(scenario)
    if problems or not isinstance(scenario, dict):
        return problems
    problems = _common_problems(scenario, THEME_SCENARIO_ACTIONS)
    steps = scenario["steps"]
    covered = {step.get("covers") for step in steps}
    uncovered = [theme_id for theme_id in THEME_IDS if theme_id not in covered]
    if uncovered:
        problems.append(f"no step covers {uncovered}")
    live = [step for step in steps if step["action"] != "dispose"]
    if not all(isinstance(step["expect"].get("theme"), dict) for step in live):
        problems.append("a step before dispose does not assert the theme")
    if not all(isinstance(step["expect"].get("events"), list) for step in steps):
        problems.append("a step does not assert its ordered events")
    return problems


def check_shared_scenario(repo_root: Path, roots: dict[str, Path]) -> int:
    problems: list[str] = []
    passed: list[str] = []
    for relative, validate, detail in (
        (SCENARIO, _scenario_problems, ""),
        (THEME_SCENARIO, _theme_scenario_problems, f", {THEME_IDS[0]}..{THEME_IDS[-1][-3:]}"),
    ):
        try:
            scenario = json.loads((repo_root / relative).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"shared scenario: cannot read {relative}: {error}")
            continue
        found = validate(scenario)
        problems.extend(f"shared scenario {relative.name}: {problem}" for problem in found)
        if not found:
            passed.append(
                f"[OK] behavioral parity: shared scenario '{scenario['id']}' "
                f"({len(scenario['steps'])} steps{detail}) runs through an adapter in 4 flavors"
            )
    for flavor, root in roots.items():
        adapter = SCENARIO_ADAPTERS[flavor]
        candidates = [candidate for candidate in root.rglob(adapter) if candidate.is_file()]
        if not candidates:
            problems.append(f"{flavor}: no shared-scenario adapter '{adapter}' under {root}")
            continue
        text = "\n".join(candidate.read_text(encoding="utf-8") for candidate in candidates)
        for relative in (SCENARIO, THEME_SCENARIO):
            if relative.name not in text:
                problems.append(f"{flavor}: '{adapter}' does not load {relative.name}")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    for line in passed:
        print(line)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repo root (default: current dir)")
    args = ap.parse_args()
    # Resolve flavor roots against the repo root. ROOTS holds repo-relative
    # subpaths and is never mutated, so main() is safe to call repeatedly.
    repo_root = Path(args.root).resolve()
    roots = {f: repo_root / r for f, r in ROOTS.items()}
    parity_result = check(roots)
    scenario_result = check_shared_scenario(repo_root, roots)
    rust_scope_result = check_rust_scope(repo_root)
    return 1 if parity_result or scenario_result or rust_scope_result else 0


if __name__ == "__main__":
    sys.exit(main())
