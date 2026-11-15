"""Unit tests for tools/check-conformance-catalog.py (#1792).

Each test builds a small repository under tmp_path: a catalog, and chapters with
Conformance sections. The fixture is structurally clean; a test breaks one rule.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import check_conformance_catalog as ccat
import pytest

CATALOG = textwrap.dedent(
    """\
    # 12 — Conformance test catalog

    ## 1. Identifier prefixes

    | Prefix      | Area                    | File              |
    | ----------- | ----------------------- | ----------------- |
    | `LIFE-NNN`  | Lifecycle state machine | `02-lifecycle.md` |
    | `GRP-NNN`   | GroupVM                 | `07-group-vm.md`  |
    | `DISP-NNN`  | Cross-cutting disposal  | `01-concepts.md`  |
    | `THEME-NNN` | Theme scenario          | `proposals/x.md`  |

    ## 2. Reading entries

    Each entry below follows Given/When/Then.

    ### 2.1 Notation conventions

    Notation text.

    ______________________________________________________________________

    ## 3. Lifecycle (`LIFE-NNN`)

    ### LIFE-001 — construct

    **Given** a freshly built VM
    **When** `construct()` is called
    **Then** the VM is `Constructed`

    ### LIFE-002 — destruct

    **Given** a constructed VM
    **When** `destruct()` is called
    **Then** the VM is `Destructed`

    ## 4. Groups (`GRP-NNN`)

    ### GRP-001 — members

    **Given** a group
    **When** a member is added
    **Then** the group lists the member

    ## 5. Disposal (`DISP-NNN`)

    ### DISP-001 — repeated disposal

    **Given** a disposed VM
    **When** `dispose()` is called again
    **Then** nothing changes

    ### DISP-002 — disposal of owned resources

    **Given** a VM with an owned resource
    **When** the VM is disposed
    **Then** the resource is disposed

    ## 6. Theme (`THEME-NNN`)

    ### THEME-001 — scenario

    **Given** an example application
    **When** the theme changes
    **Then** the view updates
    """
)

CHAPTERS = {
    "00-overview.md": textwrap.dedent(
        """\
        # 00 — Overview

        ## 1. Scope

        Text.
        """
    ),
    "01-concepts.md": textwrap.dedent(
        """\
        # 01 — Concepts

        ## 1. Overview

        Text.

        ## 5. Conformance

        Chapter 12 §5 states the cross-cutting `DISP-001` to `DISP-002` IDs.

        | IDs                    | Rules       |
        | ---------------------- | ----------- |
        | `DISP-001`..`DISP-002` | §1 overview |
        """
    ),
    "02-lifecycle.md": textwrap.dedent(
        """\
        # 02 — Lifecycle

        ## 1. States

        Text.

        ## 2. Operations

        ### 2.3 Owned resources

        Text.

        ## 3. Invariants

        Text.

        ## 9. Conformance

        Chapter 12 §3 holds the `LIFE` IDs, and §5 holds the `DISP` IDs.

        | IDs                    | Rules                               |
        | ---------------------- | ----------------------------------- |
        | `LIFE-001`..`LIFE-002` | §2 operations, §2.3 owned resources |
        | `DISP-001`             | §1 states, chapter 01 §5            |
        """
    ),
    "07-group-vm.md": textwrap.dedent(
        """\
        # 07 — Group VM

        ## 1. Members

        Text.

        ## 7. Conformance

        Chapter 12 §4 holds the `GRP` IDs.

        | IDs       | Rules      |
        | --------- | ---------- |
        | `GRP-001` | §1 members |
        """
    ),
}


def _repo(
    tmp_path: Path,
    *,
    catalog: str = CATALOG,
    chapters: dict[str, str] | None = None,
) -> Path:
    spec = tmp_path / "spec"
    spec.mkdir(parents=True, exist_ok=True)
    (spec / "12-conformance.md").write_text(catalog, encoding="utf-8")
    for name, text in {**CHAPTERS, **(chapters or {})}.items():
        (spec / name).write_text(text, encoding="utf-8")
    return tmp_path


def _replace(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"fixture text not found exactly once: {old!r}"
    return text.replace(old, new)


def _run(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = ccat.main(["--repo-root", str(root)])
    return code, capsys.readouterr().out


def _catalog_line(prefix: str) -> int:
    for number, line in enumerate(CATALOG.splitlines(), start=1):
        if line.startswith(prefix):
            return number
    raise AssertionError(f"no catalog line starts with {prefix!r}")


def test_clean_fixture_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(_repo(tmp_path), capsys)

    assert code == 0, out


def test_removed_table_row_names_the_library_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chapter = _replace(CHAPTERS["07-group-vm.md"], "| `GRP-001` | §1 members |\n", "")
    root = _repo(tmp_path, chapters={"07-group-vm.md": chapter})

    code, out = _run(root, capsys)

    heading_line = _catalog_line("### GRP-001")
    assert code == 1
    assert (
        f"spec/12-conformance.md:{heading_line}: GRP-001 is in no chapter Conformance table" in out
    )


def test_table_id_missing_from_catalog_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chapter = _replace(
        CHAPTERS["02-lifecycle.md"],
        "| `DISP-001`             |",
        "| `DISP-001`, `DISP-099` |",
    )
    root = _repo(tmp_path, chapters={"02-lifecycle.md": chapter})

    code, out = _run(root, capsys)

    assert code == 1
    assert "spec/02-lifecycle.md:" in out
    assert "table ID DISP-099 is not in the catalog" in out


def test_range_row_with_an_id_past_the_catalog_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chapter = _replace(
        CHAPTERS["02-lifecycle.md"],
        "| `LIFE-001`..`LIFE-002` |",
        "| `LIFE-001`..`LIFE-003` |",
    )
    root = _repo(tmp_path, chapters={"02-lifecycle.md": chapter})

    code, out = _run(root, capsys)

    assert code == 1
    assert "table ID LIFE-003 is not in the catalog" in out


def test_section_reference_naming_a_renamed_heading_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chapter = _replace(CHAPTERS["02-lifecycle.md"], "## 2. Operations", "## Operations")
    root = _repo(tmp_path, chapters={"02-lifecycle.md": chapter})

    code, out = _run(root, capsys)

    assert code == 1
    assert "spec/02-lifecycle.md:" in out
    assert "§2 names no heading of this chapter" in out


def test_catalog_sentence_naming_a_section_without_the_prefix_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chapter = _replace(
        CHAPTERS["02-lifecycle.md"],
        "Chapter 12 §3 holds the `LIFE` IDs",
        "Chapter 12 §4 holds the `LIFE` IDs",
    )
    root = _repo(tmp_path, chapters={"02-lifecycle.md": chapter})

    code, out = _run(root, capsys)

    assert code == 1
    assert "spec/02-lifecycle.md:" in out
    assert "§4 holds no LIFE ID" in out


def test_catalog_sentence_naming_a_prefix_no_section_holds_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chapter = _replace(
        CHAPTERS["02-lifecycle.md"],
        "and §5 holds the `DISP` IDs",
        "and §5 holds the `HUB` IDs",
    )
    root = _repo(tmp_path, chapters={"02-lifecycle.md": chapter})

    code, out = _run(root, capsys)

    assert code == 1
    assert "no HUB ID in catalog" in out


def test_catalog_sentence_range_naming_an_id_outside_the_section_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chapter = _replace(
        CHAPTERS["01-concepts.md"],
        "`DISP-001` to `DISP-002` IDs",
        "`DISP-001` to `DISP-003` IDs",
    )
    root = _repo(tmp_path, chapters={"01-concepts.md": chapter})

    code, out = _run(root, capsys)

    assert code == 1
    assert "spec/01-concepts.md:" in out
    assert "DISP-003 is not a heading of catalog §5" in out


def test_catalog_sentence_with_prefixes_held_across_sections_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Each named section holds one of the clause's prefixes, and each prefix
    # has a heading in a named section, so the clause passes as written.
    chapter = _replace(
        CHAPTERS["02-lifecycle.md"],
        "Chapter 12 §3 holds the `LIFE` IDs, and §5 holds the `DISP` IDs.",
        "Chapter 12 §3 and §5 hold the `LIFE` and `DISP` IDs.",
    )
    root = _repo(tmp_path, chapters={"02-lifecycle.md": chapter})

    code, out = _run(root, capsys)

    assert code == 0, out


@pytest.mark.parametrize(
    "heading",
    [
        "### LIFE-23",
        "### life-004",
        "### NOTIFY-001",
        "### COL-1000",
        "### DP-001",
        "###LIFE-005",
    ],
)
def test_malformed_id_heading_from_section_3_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], heading: str
) -> None:
    catalog = _replace(
        CATALOG, "## 3. Lifecycle (`LIFE-NNN`)\n", f"## 3. Lifecycle (`LIFE-NNN`)\n\n{heading}\n"
    )
    root = _repo(tmp_path, catalog=catalog)

    code, out = _run(root, capsys)

    assert code == 1
    assert f"malformed heading '{heading}'" in out


def test_section_2_numbered_heading_is_not_an_id_heading(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The clean fixture keeps `### 2.1 Notation conventions` in §2, so the
    # malformed-heading rule must not fire on it.
    code, out = _run(_repo(tmp_path), capsys)

    assert code == 0, out


def test_id_heading_with_an_unlisted_prefix_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = _replace(
        CATALOG, "## 4. Groups (`GRP-NNN`)\n", "## 4. Groups (`GRP-NNN`)\n\n### NOTIF-001 — stray\n"
    )
    root = _repo(tmp_path, catalog=catalog)

    code, out = _run(root, capsys)

    assert code == 1
    assert "NOTIF-001 prefix NOTIF is not in the §1 table" in out


def test_entry_without_given_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = _replace(CATALOG, "**Given** a freshly built VM\n", "")
    root = _repo(tmp_path, catalog=catalog)

    code, out = _run(root, capsys)

    assert code == 1
    assert "LIFE-001 has no **Given** clause" in out


def test_entry_without_then_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    catalog = _replace(CATALOG, "**Then** the VM is `Constructed`\n", "")
    root = _repo(tmp_path, catalog=catalog)

    code, out = _run(root, capsys)

    assert code == 1
    assert "LIFE-001 has no **Then** clause" in out


def test_entry_without_when_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    catalog = _replace(CATALOG, "**When** `construct()` is called\n", "")
    root = _repo(tmp_path, catalog=catalog)

    code, out = _run(root, capsys)

    assert code == 1
    assert "LIFE-001 has no **When** clause and no setup-only marker" in out


def test_setup_only_marker_stands_in_for_when(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = _replace(CATALOG, "**When** `construct()` is called\n", "**When** (setup only)\n")
    root = _repo(tmp_path, catalog=catalog)

    code, out = _run(root, capsys)

    assert code == 0, out


def test_chapter_without_conformance_section_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chapter = _replace(CHAPTERS["07-group-vm.md"], "## 7. Conformance", "## 7. Coverage")
    root = _repo(tmp_path, chapters={"07-group-vm.md": chapter})

    code, out = _run(root, capsys)

    assert code == 1
    assert "spec/07-group-vm.md:1: no `## N. Conformance` section" in out


def test_missing_catalog_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "spec").mkdir()

    code, _ = _run(tmp_path, capsys)

    assert code == 2


def test_repository_catalog_passes() -> None:
    # The checked-in catalog and chapters must satisfy the rules CI enforces.
    assert ccat.main([]) == 0
